"""From a fresh clone to a running platform, in one command.

    python scripts/bootstrap.py all --months 2024-12..2025-05
    python scripts/bootstrap.py all --months 2025-01..2025-06 --gpu --model qwen2.5:7b

Steps (each can be run alone, each is safe to run again):
  env    create .env from .env.example with random secrets (never overwrites .env)
  core   PostgreSQL + RustFS, taxi zones
  load   Airflow; one pipeline run per month, in order, each waited for
  bi     Superset; datasets, metrics and the six dashboards built from the publication
  ai     Ollama (model downloaded and loaded) + assistant API, health checked
  all    every step above

Only the Python standard library and Docker are needed (Windows, macOS or Linux).
--low-memory stops the services of a step before the next one starts (8 GB laptops).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV, ENV_EXAMPLE = ROOT / ".env", ROOT / ".env.example"
DAG = "monthly_yellow_pipeline"
PROFILES = {
    "core": ["core"],
    "tools": ["core", "tools"],
    "load": ["core", "orchestration"],
    "bi": ["core", "orchestration", "bi"],
    "ai": ["core", "ai"],
}


def say(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def compose(group: str, *args: str, capture: bool = False, check: bool = True) -> str:
    cmd = ["docker", "compose"]
    for profile in PROFILES[group]:
        cmd += ["--profile", profile]
    cmd += list(args)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    if check and result.returncode:
        detail = (result.stderr or "").strip()[-800:] if capture else ""
        raise SystemExit(f"failed ({result.returncode}): {' '.join(cmd)}\n{detail}")
    return result.stdout if capture else ""


def airflow(*args: str) -> str:
    return compose("load", "exec", "-T", "airflow-scheduler", "airflow", *args, capture=True)


# ----------------------------------------------------------------------------- env
def fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def make_env(model: str | None, gpu: bool, max_tasks: int | None) -> None:
    if ENV.exists():
        say(".env already exists: kept as it is (delete it to generate a new one)")
        return
    lines = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            if key == "AIRFLOW_FERNET_KEY":
                value = fernet_key()
            elif value == "change_me":
                value = secrets.token_urlsafe(32)
            elif key == "OLLAMA_MODEL" and model:
                value = model
            elif key == "PIPELINE_MAX_ACTIVE_TASKS" and max_tasks:
                value = str(max_tasks)
            elif key == "PIPELINE_SCHEDULE":
                value = ""  # manual runs while the history is loaded; set the cron after
            line = f"{key}={value}"
        lines.append(line)
    if gpu:
        separator = ";" if os.name == "nt" else ":"
        lines += [
            "",
            "# GPU host: Ollama gets the NVIDIA GPU (docker-compose.gpu.yml)",
            f"COMPOSE_FILE=docker-compose.yml{separator}docker-compose.gpu.yml",
        ]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(".env created with random secrets (it is git-ignored; keep it private)")


def env_value(key: str) -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name == key:
            return value
    return ""


# ----------------------------------------------------------------------------- steps
def core() -> None:
    say("core services: PostgreSQL and RustFS")
    compose("core", "up", "-d", "--wait")
    say("taxi zones")
    compose("tools", "run", "--rm", "-T", "ingestion", "zones")


def month_list(spec: str) -> list[str]:
    """'2024-12..2025-03' or '2025-01,2025-02' -> ['2024-12', '2025-01', ...]."""
    if ".." in spec:
        start, end = spec.split("..")
        y, m = map(int, start.split("-"))
        ey, em = map(int, end.split("-"))
        months = []
        while (y, m) <= (ey, em):
            months.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return months
    return [m.strip() for m in spec.split(",") if m.strip()]


def run_state(run_id: str) -> str | None:
    out = airflow("dags", "list-runs", DAG, "-o", "json")
    match = re.search(r"\[.*\]", out, re.S)
    runs = json.loads(match.group(0)) if match else []
    return next((r["state"] for r in runs if r["run_id"] == run_id), None)


def airflow_ready(timeout_s: int = 1800) -> None:
    """Wait until the Airflow CLI answers and the DAG is parsed. Not `up --wait`: on a busy
    host the DAG processor's own health check can time out while it works normally."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        out = compose(
            "load", "exec", "-T", "airflow-scheduler", "airflow", "dags", "list", "-o", "plain",
            capture=True, check=False,
        )  # fmt: skip
        if DAG in out:
            return
        time.sleep(30)
    raise SystemExit("Airflow did not list the pipeline DAG in time: see its logs")


def load(months: list[str], timeout_h: float) -> None:
    say("Airflow (first start runs the database migration and dbt parse)")
    compose("load", "up", "-d")
    airflow_ready()
    airflow("dags", "unpause", DAG)
    for month in months:
        run_id = f"load_{month.replace('-', '_')}"
        state = run_state(run_id)
        if state == "success":
            say(f"{month}: already loaded ({run_id})")
            continue
        if state is None:
            say(f"{month}: pipeline run {run_id}")
            airflow(
                "dags", "trigger", DAG, "--run-id", run_id,
                "--conf", json.dumps({"month": month, "force": False}),
            )  # fmt: skip
        deadline = time.monotonic() + timeout_h * 3600
        while (state := run_state(run_id)) not in ("success", "failed"):
            if time.monotonic() > deadline:
                raise SystemExit(f"{run_id} still {state} after {timeout_h} h: see Airflow")
            time.sleep(60)
        if state == "failed":
            raise SystemExit(f"{run_id} failed: open Airflow on port {env_value('AIRFLOW_PORT')}")
        say(f"{month}: published")


def bi() -> None:
    say("Superset")
    compose("bi", "up", "-d", "--wait")
    say("datasets, governed metrics and the six dashboards (DAG refresh_dashboards)")
    airflow("dags", "unpause", "refresh_dashboards")
    run_id = f"bootstrap_{int(time.time())}"
    airflow("dags", "trigger", "refresh_dashboards", "--run-id", run_id)
    while True:
        out = airflow("dags", "list-runs", "refresh_dashboards", "-o", "json")
        match = re.search(r"\[.*\]", out, re.S)
        runs = json.loads(match.group(0)) if match else []
        state = next((r["state"] for r in runs if r["run_id"] == run_id), None)
        if state in ("success", "failed"):
            break
        time.sleep(30)
    if state == "failed":
        raise SystemExit("refresh_dashboards failed: see its log in Airflow")


def ai() -> None:
    say(f"Ollama: download and load {env_value('OLLAMA_MODEL')} (minutes on a CPU)")
    compose("ai", "up", "-d", "--wait", "ollama")
    compose("ai", "run", "--rm", "-T", "ollama-pull")
    say("assistant API")
    compose("ai", "up", "-d", "--wait", "api")
    url = f"http://localhost:{env_value('API_PORT') or '8000'}/health"
    with urllib.request.urlopen(url, timeout=30) as response:
        health = json.loads(response.read())
    print(json.dumps(health, indent=2))
    if health.get("status") != "ok" or not health.get("model_available"):
        raise SystemExit("assistant not healthy: see `docker compose logs api ollama`")


def summary() -> None:
    say("ready")
    for name, port, path, login in (
        ("Airflow", "AIRFLOW_PORT", "", "admin / AIRFLOW_ADMIN_PASSWORD"),
        ("Superset", "SUPERSET_PORT", "", "admin / SUPERSET_ADMIN_PASSWORD"),
        ("API docs", "API_PORT", "/docs", "Bearer API_TOKEN"),
    ):
        print(f"  {name:<9} http://localhost:{env_value(port)}{path}  ({login})")
    print("  Passwords are in .env.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["env", "core", "load", "bi", "ai", "all"])
    parser.add_argument("--months", default="2024-12..2025-02", help="YYYY-MM..YYYY-MM or a list")
    parser.add_argument("--model", help="Ollama model written to a new .env, e.g. qwen2.5:7b")
    parser.add_argument("--gpu", action="store_true", help="give the NVIDIA GPU to Ollama")
    parser.add_argument("--max-active-tasks", type=int, help="parallel Airflow tasks (new .env)")
    parser.add_argument("--run-timeout-h", type=float, default=8, help="limit per monthly run")
    parser.add_argument("--low-memory", action="store_true", help="stop each step's services")
    args = parser.parse_args(argv)

    make_env(args.model, args.gpu, args.max_active_tasks)
    if args.step == "env":
        return 0
    if args.step in ("core", "all"):
        core()
    if args.step in ("load", "all"):
        load(month_list(args.months), args.run_timeout_h)
    if args.step in ("bi", "all"):
        bi()
        if args.low_memory:
            compose("bi", "stop", "superset", "redis", "airflow-scheduler", "airflow-dag-processor")
    if args.step in ("ai", "all"):
        ai()
    summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
