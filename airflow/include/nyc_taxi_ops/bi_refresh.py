"""Refresh Superset after a publication, so the dashboards never show the previous month.

Three commands of services/metrics_sync, run in the ingestion virtual environment (it has
httpx and psycopg):
  1. metrics_sync.py database  the metric catalogue read by the AI assistant
  2. superset_sync.py          certified datasets and metrics; updating a dataset changes
                               its last-change time, which is part of Superset's cache
                               key, so cached chart results of the previous publication
                               are no longer served
  3. dashboards.py             charts, layout and "So what?" texts recomputed from the new
                               publication; every chart query runs once (cache warm-up)

Superset not running is not an error (the data is published; the dashboards are refreshed
by the refresh_dashboards DAG when Superset starts). A refresh that fails is an error.
"""

from __future__ import annotations

import logging
import os
import subprocess
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

METRICS_SYNC_DIR = Path(os.environ.get("METRICS_SYNC_DIR", "/opt/airflow/metrics_sync"))
PYTHON = os.environ.get("BI_REFRESH_PYTHON", "/opt/ingestion_venv/bin/python")
SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://superset:8088")

REFRESHED = "refreshed"
SUPERSET_DOWN = "superset_not_running"


def superset_running(url: str = SUPERSET_URL, timeout: float = 10) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as response:
            return response.status == 200
    except OSError:
        return False


def commands(manifest: Path) -> list[list[str]]:
    return [
        [PYTHON, "metrics_sync.py", "database", "--manifest", str(manifest)],
        [PYTHON, "superset_sync.py", "--manifest", str(manifest)],
        [PYTHON, "dashboards.py"],
    ]


def command_env(host: str, port: int, database: str, user: str, password: str) -> dict:
    """Environment of the commands: the publisher connection for the metric catalogue."""
    return os.environ | {
        "PGHOST": host,
        "PGPORT": str(port),
        "PGDATABASE": database,
        "PGUSER": user,
        "PGPASSWORD": password,
        "PYTHONDONTWRITEBYTECODE": "1",  # the code folder is mounted read-only
    }


def refresh(env: dict, manifest: Path) -> str:
    if not superset_running():
        log.warning("Superset is not running: dashboards not refreshed")
        return SUPERSET_DOWN
    for cmd in commands(manifest):
        result = subprocess.run(cmd, cwd=METRICS_SYNC_DIR, env=env, capture_output=True, text=True)
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
            raise RuntimeError(f"{cmd[1]} failed with exit code {result.returncode}")
    return REFRESHED


def dashboards_status(published: bool, result: str | None) -> str | None:
    """What the run summary says about the dashboards (None: nothing was published).

    result is the return value of the refresh task: None when it failed or did not run.
    """
    if not published:
        return None
    if result == REFRESHED:
        return "refreshed"
    if result == SUPERSET_DOWN:
        return "not refreshed: Superset not running (trigger refresh_dashboards when it starts)"
    return "refresh failed"
