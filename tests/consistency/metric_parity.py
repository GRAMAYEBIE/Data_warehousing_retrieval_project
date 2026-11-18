"""Metric parity check (exam Q6.4): the same metric must give the same value everywhere.

Surfaces compared, month by month:
  1. dbt / MetricFlow  `mf query` on gold.fct_trip (row level, the semantic layer)
  2. published SQL     meta.sql_expression of the metric over the analytics aggregates,
                       read with the AI read-only role (what Superset and the AI use)
  3. Superset          chart data API, when SUPERSET_URL is set (wave 4)

Runs in the dbt container (MetricFlow CLI and psycopg2 are installed there):
    docker compose --profile core --profile tools run --rm \
        -e AI_READER_PASSWORD -v ./tests:/tests -v ./docs:/docs \
        --entrypoint python dbt /tests/consistency/metric_parity.py

Exit code 0 when every value matches, 1 otherwise. Writes docs/evidence/q06/reconciliation.md.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg2

METRICS = [
    "trips",
    "total_revenue",
    "avg_fare",
    "tip_rate",
    "valid_trip_rate",
    "trips_per_active_hour",
    "congestion_fee_revenue",
    "est_co2_kg",
]
RELATIVE_TOLERANCE = Decimal("1e-9")
PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "/usr/app/dbt"))
OUTPUT = Path(os.environ.get("PARITY_OUTPUT", "/docs/evidence/q06/reconciliation.md"))


def metricflow_values() -> dict[tuple[str, date], Decimal]:
    """Run mf query once for all metrics, grouped by month."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "mf.csv"
        cmd = [
            "mf",
            "query",
            "--metrics",
            ",".join(METRICS),
            "--group-by",
            "metric_time__month",
            "--csv",
            str(out),
        ]
        result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
        if result.returncode != 0 or not out.exists():
            print(result.stdout[-3000:], result.stderr[-3000:], sep="\n")
            raise SystemExit("mf query failed")
        values = {}
        with out.open(newline="") as handle:
            for row in csv.DictReader(handle):
                month = date.fromisoformat(row["metric_time__month"][:10])
                for metric in METRICS:
                    if row.get(metric) not in (None, ""):
                        values[(metric, month)] = Decimal(row[metric])
    return values


def published_values(
    catalog: dict[str, dict],
) -> tuple[dict[tuple[str, date], Decimal], tuple[str, datetime]]:
    """Each metric's sql_expression over its analytics table, as the AI role."""
    conn = psycopg2.connect(
        host=os.environ.get("DBT_HOST", "postgres"),
        dbname=os.environ.get("DBT_DATABASE", "warehouse"),
        user="ai_reader",
        password=os.environ["AI_READER_PASSWORD"],
    )
    values = {}
    with conn, conn.cursor() as cur:
        for metric in METRICS:
            entry = catalog[metric]
            cur.execute(
                f"""
                SELECT d.month_start, {entry["sql_expression"]}
                FROM {entry["base_table"]} AS a
                JOIN analytics.dim_date AS d ON a.pickup_date_sk = d.date_sk
                WHERE d.month_start IS NOT NULL
                GROUP BY d.month_start
                """
            )
            for month, value in cur.fetchall():
                if value is not None:
                    values[(metric, month)] = Decimal(str(value))
        cur.execute("SELECT run_id, published_at FROM analytics.pipeline_status")
        publication = cur.fetchone()
    conn.close()
    return values, publication


def load_catalog() -> dict[str, dict]:
    manifest = json.loads((PROJECT_DIR / "target" / "semantic_manifest.json").read_text())
    return {m["name"]: m["config"]["meta"] for m in manifest["metrics"]}


def fmt(value: Decimal | None) -> str:
    return "-" if value is None else f"{value:,.6f}".rstrip("0").rstrip(".")


def loaded_source_months() -> set[date]:
    """Months whose source file is loaded (complete months)."""
    conn = psycopg2.connect(
        host=os.environ.get("DBT_HOST", "postgres"),
        dbname=os.environ.get("DBT_DATABASE", "warehouse"),
        user="ai_reader",
        password=os.environ["AI_READER_PASSWORD"],
    )
    with conn, conn.cursor() as cur:
        cur.execute("SELECT source_month FROM analytics.recon_bronze_silver")
        months = {row[0] for row in cur.fetchall()}
    conn.close()
    return months


def same(a: Decimal, b: Decimal) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b), Decimal(1))
    return abs(a - b) / scale <= RELATIVE_TOLERANCE


def main() -> int:
    catalog = load_catalog()
    mf = metricflow_values()
    published, publication = published_values(catalog)
    months = sorted({month for (_, month) in published})

    loaded = loaded_source_months()
    rows, mismatches = [], 0
    for month in months:
        for metric in METRICS:
            a, b = mf.get((metric, month)), published.get((metric, month))
            if a is None and b is None:
                # Both surfaces agree there is no value (e.g. the CBD fee before 2025-01).
                ok, result = True, "match (no value on either surface)"
            else:
                ok = a is not None and b is not None and same(a, b)
                result = "match" if ok else "MISMATCH"
            mismatches += not ok
            label = f"{month:%Y-%m}" + ("" if month in loaded else " (partial)")
            rows.append((label, metric, a, b, result))

    lines = [
        "# Metric parity: same metric, same value on every surface (Q6.4)",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by "
        "`tests/consistency/metric_parity.py`.",
        f"Published layer: run `{publication[0]}`, published {publication[1]:%Y-%m-%d %H:%M} UTC.",
        "",
        "- **dbt / MetricFlow**: `mf query --group-by metric_time__month` on `gold.fct_trip`.",
        "- **Published SQL**: the metric's `sql_expression` from the dbt YAML over the",
        "  `analytics` aggregates, run as `ai_reader` (the AI assistant's read-only role).",
        "- **Superset**: added in wave 4 (chart data API).",
        "",
        f"Tolerance: relative difference at most {RELATIVE_TOLERANCE}. "
        f"Result: **{len(rows) - mismatches} of {len(rows)} values match**.",
        "",
        "Months marked *partial* have no source file loaded: they only hold valid trips",
        "picked up a few hours before or after a loaded month (cross-month rows, counted",
        "on their real pickup date). Dashboards and the AI assistant show complete months",
        "only; the rows are kept here to prove both surfaces treat them identically.",
        "",
        "| Pickup month | Metric | dbt / MetricFlow | Published SQL | Result |",
        "|---|---|---|---|---|",
    ]
    for label, metric, a, b, result in rows:
        lines.append(f"| {label} | `{metric}` | {fmt(a)} | {fmt(b)} | {result} |")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines[-len(rows) - 2 :]))
    print(f"\n{len(rows) - mismatches}/{len(rows)} match -> {OUTPUT}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
