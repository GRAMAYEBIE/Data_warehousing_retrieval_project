"""Run the evaluation pack against the running assistant API (exam Q10).

    python evals/run_evals.py --api http://localhost:8000 --token $API_TOKEN \
        [--variant v3_structured_examples] [--skip-model-down] [--skip-report]

Writes docs/evidence/q10/eval_results.md and exits 1 when a case fails.
Cases marked model_down need Ollama stopped: they are run last, separately, with
--only-model-down after `docker compose stop ollama`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]


def as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def check(case: dict, response: dict) -> tuple[bool, list[str]]:
    expect, notes = case["expect"], []
    status = response.get("status")
    ok = status in as_list(expect["status"])
    if not ok:
        notes.append(f"status {status}, expected {expect['status']}")
    plan = response.get("plan") or {}
    if status == "answered":
        if "intent" in expect and plan.get("intent") != expect["intent"]:
            notes.append(f"intent {plan.get('intent')}, expected {expect['intent']}")
            ok = False
        for metric in expect.get("metrics", []):
            if metric not in plan.get("metrics", []):
                notes.append(f"metric {metric} missing from plan {plan.get('metrics')}")
                ok = False
        if expect.get("metrics_any") and not set(expect["metrics_any"]) & set(plan.get("metrics", [])):
            notes.append(f"none of {expect['metrics_any']} in plan")
            ok = False
        for dim in expect.get("dimensions", []):
            if dim not in plan.get("dimensions", []):
                notes.append(f"dimension {dim} missing")
                ok = False
        active = {f["dimension"]: f["values"] for f in response.get("active_filters", [])}
        for dim, values in expect.get("filters", {}).items():
            if active.get(dim) != values:
                notes.append(f"filter {dim}={active.get(dim)}, expected {values}")
                ok = False
        if not response.get("provenance"):
            notes.append("no provenance")
            ok = False
    reasons = " ".join(response.get("reasons") or []).lower()
    if "reason_contains" in expect and expect["reason_contains"].lower() not in reasons:
        notes.append(f"reason does not mention '{expect['reason_contains']}'")
        ok = False
    if status == "rejected" and "reason_contains_if_rejected" in expect \
            and expect["reason_contains_if_rejected"] not in reasons:
        notes.append("rejected for another reason")
        ok = False
    return ok, notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--skip-model-down", action="store_true")
    parser.add_argument("--only-model-down", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    parser.add_argument("--out", default=str(ROOT / "docs/evidence/q10/eval_results.md"))
    args = parser.parse_args()

    cases = yaml.safe_load((ROOT / "evals/cases.yaml").read_text(encoding="utf-8"))["cases"]
    http = httpx.Client(base_url=args.api, timeout=600,
                        headers={"Authorization": f"Bearer {args.token}"})
    sessions: dict[str, str] = {}
    results = []
    for case in cases:
        if case.get("model_down") and args.skip_model_down:
            continue
        if args.only_model_down and not case.get("model_down"):
            continue
        if case.get("report") and args.skip_report:
            continue
        start = time.monotonic()
        if case.get("report"):
            r = http.post("/reports", json={"request": case["question"]})
            body = r.json()
            response = body if r.status_code == 200 else {
                "status": (body.get("detail") or {}).get("status", f"http_{r.status_code}")
                if isinstance(body.get("detail"), dict) else f"http_{r.status_code}",
                "reasons": (body.get("detail") or {}).get("reasons", [str(body.get("detail"))])
                if isinstance(body.get("detail"), dict) else [str(body.get("detail"))],
            }
            if r.status_code == 200:
                response["status"] = "draft_created" if body.get("status") == "draft" else body["status"]
        else:
            key = case.get("session")
            if key and key in sessions:
                sid = sessions[key]
            else:
                sid = http.post("/sessions").json()["session_id"]
                if key:
                    sessions[key] = sid
            payload = {"question": case["question"]}
            if args.variant:
                payload["prompt_variant"] = args.variant
            response = http.post(f"/sessions/{sid}/ask", json=payload).json()
        ok, notes = check(case, response)
        seconds = round(time.monotonic() - start, 1)
        results.append({"case": case, "response": response, "ok": ok, "notes": notes,
                        "seconds": seconds})
        print(f"{case['id']:>3} {'PASS' if ok else 'FAIL'} {seconds:>6}s "
              f"{response.get('status')} {'; '.join(notes)}")

    passed = sum(r["ok"] for r in results)
    lines = [
        "# Evaluation results (exam Q10)",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, prompt variant "
        f"`{args.variant or 'default'}`. **{passed} of {len(results)} cases pass.**",
        "",
        "| Case | Category | Question | Expected | Observed | Plan | Narrative check | Time | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        c, resp = r["case"], r["response"]
        plan = resp.get("plan") or {}
        plan_txt = (f"{plan.get('intent', '')} {','.join(plan.get('metrics', []))}"
                    f" by {','.join(plan.get('dimensions', []))}").strip() if plan else "-"
        lines.append(
            f"| {c['id']} | {c['category']} | {c['question']} | {c['expect']['status']} | "
            f"{resp.get('status')} {('(' + '; '.join(resp.get('reasons') or []) + ')') if resp.get('reasons') else ''} | "
            f"{plan_txt} | {resp.get('narrative_check', '-')} | {r['seconds']} s | "
            f"{'PASS' if r['ok'] else 'FAIL: ' + '; '.join(r['notes'])} |"
        )
    lines += ["", "## Expected behaviour per case", ""]
    lines += [f"- **{r['case']['id']}**: {r['case']['behaviour']}" for r in results]
    lines += ["", "## Raw responses", "", "```json",
              json.dumps([{"id": r["case"]["id"], "response": r["response"]} for r in results],
                         indent=1, default=str)[:60000], "```"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{passed}/{len(results)} passed -> {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
