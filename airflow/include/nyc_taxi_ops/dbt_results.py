"""Record the dbt test results of each Cosmos task in ops.dbt_test_results.

Cosmos runs every dbt command in a temporary copy of the project; after the command,
its callback receives that directory. run_results.json there lists every executed node
with its status, so the test pass rate of a run can be measured without re-running tests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def test_results(run_results: dict) -> list[dict]:
    """Test nodes of a dbt run_results.json document."""
    rows = []
    for result in run_results.get("results", []):
        unique_id = result.get("unique_id", "")
        if not unique_id.startswith("test."):
            continue
        rows.append(
            {
                "unique_id": unique_id,
                "status": result.get("status"),
                "failures": result.get("failures"),
                "execution_time": result.get("execution_time"),
                "message": result.get("message"),
            }
        )
    return rows


def read_run_results(project_dir: str) -> dict:
    path = Path(project_dir) / "target" / "run_results.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def store(conn, run_id: str, rows: list[dict]) -> int:
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO ops.dbt_test_results
                    (run_id, unique_id, status, failures, execution_time, message)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, unique_id) DO UPDATE SET
                    status = EXCLUDED.status, failures = EXCLUDED.failures,
                    execution_time = EXCLUDED.execution_time, message = EXCLUDED.message,
                    recorded_at = now()
                """,
                (
                    run_id,
                    row["unique_id"],
                    row["status"],
                    row["failures"],
                    row["execution_time"],
                    row["message"],
                ),
            )
    conn.commit()
    return len(rows)
