"""Metric parity, fourth surface (exam Q6.4): the AI assistant.

metric_parity.py already shows the same value in MetricFlow (dbt), the published SQL and
Superset (docs/evidence/q06/reconciliation.md). This script asks the running assistant
for the same metric and month in plain English and compares the value it returns with the
MetricFlow value of that table. It appends the result to the reconciliation file.

    docker compose --profile core --profile tools run --rm -T -v "$PWD:/repo" -w /repo \
        --entrypoint python ingestion tests/consistency/assistant_parity.py --token "$API_TOKEN"
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

RECONCILIATION = Path("docs/evidence/q06/reconciliation.md")
QUESTIONS = {
    "trips": "How many trips did we have in {month_name}?",
    "total_revenue": "What was the total revenue in {month_name}?",
    "avg_fare": "What was the average fare in {month_name}?",
}
TOLERANCE = Decimal("1e-6")  # relative; the assistant returns the database value unchanged


def metricflow_values(month: str) -> dict[str, Decimal]:
    """MetricFlow column of the three-surface table, for one month."""
    values = {}
    for line in RECONCILIATION.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == month:
            metric = cells[1].strip("`")
            if metric in QUESTIONS:
                values[metric] = Decimal(cells[2].replace(",", ""))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://api:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--month", default="2025-01")
    args = parser.parse_args()
    http = httpx.Client(
        base_url=args.api, timeout=1800, headers={"Authorization": f"Bearer {args.token}"}
    )
    expected = metricflow_values(args.month)
    month_name = datetime.strptime(args.month, "%Y-%m").strftime("%B %Y")
    rows, failures = [], 0
    for metric, template in QUESTIONS.items():
        question = template.format(month_name=month_name)
        session = http.post("/sessions").json()["session_id"]
        answer = http.post(f"/sessions/{session}/ask", json={"question": question}).json()
        plan = answer.get("plan") or {}
        value = None
        if answer.get("status") == "answered" and metric in answer.get("columns", []):
            value = Decimal(str(answer["rows"][0][answer["columns"].index(metric)]))
        mf = expected.get(metric)
        ok = (
            value is not None
            and mf is not None
            and abs(value - mf) <= abs(mf) * TOLERANCE + Decimal("0.000001")
        )
        failures += not ok
        months = (answer.get("provenance") or {}).get("source_months")
        rows.append(
            f"| {args.month} | `{metric}` | {question} | {mf} | {value} | "
            f"{plan.get('metrics')} {months} | {'match' if ok else 'MISMATCH'} |"
        )
        print(rows[-1], flush=True)
    section = [
        "",
        f"## Fourth surface: the AI assistant ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)",
        "",
        "The question is asked in plain English to the running assistant; its value is",
        "compared with the MetricFlow value of the table above.",
        "",
        "| Month | Metric | Question | MetricFlow | Assistant | Plan and months | Result |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
        f"{len(rows) - failures}/{len(rows)} match.",
    ]
    text = RECONCILIATION.read_text(encoding="utf-8")
    text = re.split(r"\n## Fourth surface: the AI assistant", text)[0].rstrip("\n")
    RECONCILIATION.write_text(text + "\n" + "\n".join(section) + "\n", encoding="utf-8")
    print(f"{len(rows) - failures}/{len(rows)} match -> {RECONCILIATION}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
