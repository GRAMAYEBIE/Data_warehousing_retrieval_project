"""Generate docs/data_dictionary.md from the dbt documentation (docs/dbt_docs).

    python scripts/data_dictionary.py

Descriptions come from the dbt YAML (manifest.json), column types from the warehouse
itself (catalog.json, written by `dbt docs generate`), so the dictionary always matches the
models. Run it again after `dbt docs generate` when a model changes.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "dbt_docs"
OUT = ROOT / "docs" / "data_dictionary.md"

LAYERS = [
    ("Silver: staging", "models/staging/"),
    ("Silver: cleaned and flagged trips", "models/intermediate/"),
    ("Gold: fact table", "models/marts/fact/"),
    ("Gold: dimensions", "models/marts/dim_"),
    ("Gold: aggregates and reconciliation", "models/marts/"),
    ("Semantic layer support", "models/semantic/"),
]

EXTRA = """
## Published layer (`analytics`)

Written by the publication task (`airflow/include/nyc_taxi_ops/publish.py`), never by dbt:
a copy of the approved gold tables (same columns as above), swapped in one transaction
after the quality gate, plus BI views that join them to their dimensions. Superset and the
AI assistant read this schema only.

| Object | Content |
|---|---|
| `pipeline_status` | the publication in service: run id, time, months published |
| `mv_trips_daily`, `mv_trips_hourly`, `mv_routes_monthly`, `mv_quality_daily` | the aggregates joined to their dimensions, complete months only |
| `mv_revenue_bridge` | previous month's revenue, volume effect and price effect |
| `mv_dropoff_growth` | fastest-growing and fastest-declining drop-off zones |
| `mv_route_duration_anomaly` | routes slower than usual (robust z-score) |

## Forecasts (`ml`, written by the role `forecaster`)

Estimates, never governed measures (`ml/src/forecasting/store.py`, `check.py`).

| Table | Grain | Content |
|---|---|---|
| `forecast_run` | one forecasting run (MLflow run id) | target, data publication, months, champion, decision, replay flag |
| `forecast_backtest` | run × test month × method × segment | error (WMAPE), bias and 80 % coverage of each method on each backtest month |
| `forecast_evaluation` | run × segment | the champion's scores on the last month |
| `demand_forecast`, `revenue_forecast` | run × zone × day × hour | expected trips (or USD), 80 % range, demand tier, low-confidence flag, method |
| `demand_forecast_daily`, `revenue_forecast_daily` | run × borough × day | expected value and 80 % range |
| `forecast_check_run` | checked month | expected and observed error per borough and day, status (ok or drift) |
| `forecast_check` | checked month × segment | recorded and forecast totals, error, bias, coverage |
| `forecast_check_daily` | checked month × borough × day | forecast, range and recorded value |

## Streaming (`stream`, written by the role `streamer`)

Provisional rows of the current month, received through Kafka; never in silver, gold or a
governed measure (`infra/postgres/init/09_stream.sql`).

| Table | Grain | Content |
|---|---|---|
| `yellow_trips` | one trip (source month, row of the file) | pickup and drop-off times and zones, distance, payment, fare, tip, total, Kafka partition and offset, received at |
| `yellow_trips_rejects` | one rejected message | reason, raw message, Kafka position |

## Operations (`ops`)

| Table | Content |
|---|---|
| `ingestion_manifest` | one row per ingestion attempt: status, row counts, checksum, schema version and hash, drift report, errors |
| `pipeline_runs`, `pipeline_signals`, `publications` | Airflow runs, operational signals, batches published |
| `dbt_test_results` | the result of every dbt test of every run |
| `ai_audit_log` | every question to the assistant: plan, verdict, SQL, durations, trace id |
"""


# Descriptions of columns the YAML does not document (TLC data dictionary for the source
# fields, the project's conventions for the rest).
COMMON = {
    "vendorid": "TLC code of the technology provider (1 Creative Mobile, 2 Curb, 6 Myle, 7 Helix).",
    "vendor_id": "TLC code of the technology provider (1 Creative Mobile, 2 Curb, 6 Myle, 7 Helix).",
    "tpep_pickup_datetime": "Meter engaged, New York local time, as published.",
    "tpep_dropoff_datetime": "Meter disengaged, New York local time, as published.",
    "pickup_ts": "Pickup time (meter engaged), New York local time.",
    "dropoff_ts": "Drop-off time (meter disengaged), New York local time.",
    "passenger_count": "Number of passengers entered by the driver (not reported for some trips).",
    "trip_distance": "Distance in miles reported by the taximeter.",
    "ratecodeid": "Final rate code (1 standard, 2 JFK, 3 Newark, 4 Nassau/Westchester, 5 negotiated, 6 group ride, 99 unknown).",
    "rate_code_id": "Final rate code (1 standard, 2 JFK, 3 Newark, 4 Nassau/Westchester, 5 negotiated, 6 group ride, 99 unknown).",
    "store_and_fwd_flag": "Y when the trip was stored in the vehicle before being sent (no connection).",
    "pulocationid": "TLC taxi zone of the pickup.",
    "dolocationid": "TLC taxi zone of the drop-off.",
    "pickup_location_id": "TLC taxi zone of the pickup.",
    "dropoff_location_id": "TLC taxi zone of the drop-off.",
    "payment_type": "Payment code (0 flex fare / not reported, 1 card, 2 cash, 3 no charge, 4 dispute, 5 unknown, 6 voided).",
    "payment_type_id": "Payment code (0 flex fare / not reported, 1 card, 2 cash, 3 no charge, 4 dispute, 5 unknown, 6 voided).",
    "fare_amount": "Time-and-distance fare calculated by the meter, USD.",
    "extra": "Miscellaneous extras and surcharges, USD (vendor 1 includes congestion charges here).",
    "extra_amount": "Miscellaneous extras and surcharges, USD (vendor 1 includes congestion charges here).",
    "mta_tax": "MTA tax, USD.",
    "tip_amount": "Tip, USD; recorded for card payments only.",
    "tolls_amount": "Tolls paid, USD.",
    "improvement_surcharge": "Improvement surcharge, USD.",
    "total_amount": "Total charged to the passenger, USD (cash tips excluded); the governed revenue measure.",
    "congestion_surcharge": "New York State congestion surcharge, USD.",
    "airport_fee": "Airport fee for pickups at LaGuardia and JFK, USD.",
    "cbd_congestion_fee": "MTA Congestion Relief Zone toll, from 5 January 2025, USD.",
    "duration_min": "Trip duration in minutes (drop-off minus pickup).",
    "speed_mph": "Average speed, miles per hour (distance / duration).",
    "source_file": "Name of the monthly Parquet file the row comes from.",
    "source_month": "First day of the month of the source file.",
    "file_row_number": "0-based position of the row in the source file.",
    "batch_id": "Ingestion batch that loaded the row (ops.ingestion_manifest).",
    "ingested_at": "Time the row was loaded into bronze.",
    "silver_loaded_at": "Time the row was written to silver.",
    "gold_loaded_at": "Time the row was written to gold.",
    "schema_hash": "SHA-256 of the file's sorted column names and types (schema drift detection).",
    "extra_columns": "Columns the contract does not know, kept as JSON (schema drift).",
    "quality_status": "valid, suspicious or invalid, from the highest severity among the flags.",
    "quality_flags": "Codes of the quality flags raised on the trip.",
    "trip_count": "Number of trips (sum at read time).",
    "date_day": "Calendar day.",
    "month_start": "First day of the month.",
    "week_start": "Monday of the week.",
    "pickup_hour": "Hour of the pickup (0 to 23).",
    "borough": "Borough of the zone.",
    "zone": "Name of the taxi zone.",
    "zone_name": "Name of the taxi zone.",
    "service_zone": "TLC service zone (Yellow Zone, Boro Zone, Airports, EWR).",
    "market_segment": "Airport, Manhattan core or outer borough.",
    "is_weekend": "True on Saturday and Sunday.",
    "is_holiday": "True on a US federal or New York State public holiday.",
    "holiday_name": "Name of the public holiday.",
    "is_airport_trip": "Pickup or drop-off at EWR, JFK or LaGuardia, or a JFK / Newark rate code.",
    "is_tip_recorded": "True for card payments, the only ones whose tips are recorded.",
    "locationid": "TLC taxi zone id (1 to 265; 264 and 265 are unknown).",
    "location_id": "TLC taxi zone id (1 to 265; 264 and 265 are unknown).",
    "pickup_zone": "Name of the pickup zone.",
    "dropoff_zone": "Name of the drop-off zone.",
    "pickup_borough": "Borough of the pickup zone.",
    "dropoff_borough": "Borough of the drop-off zone.",
    "pickup_service_zone": "TLC service zone of the pickup.",
    "dropoff_service_zone": "TLC service zone of the drop-off.",
    "pickup_market_segment": "Market segment of the pickup zone (airport, Manhattan core, outer borough).",
    "dropoff_market_segment": "Market segment of the drop-off zone.",
    "pickup_month": "Month of the pickup (first day).",
    "day_of_week": "Day of the week (1 Monday to 7 Sunday).",
    "year_number": "Calendar year.",
    "quarter_number": "Calendar quarter (1 to 4).",
    "month_number": "Calendar month (1 to 12).",
    "hour_of_day": "Hour (0 to 23).",
    "minute_of_hour": "Minute within the hour (0 to 59).",
    "time_of_day": "Time as HH:MM.",
    "day_part": "Night, morning, afternoon or evening.",
    "service_period_rule": "Hours that define the service period.",
    "has_cast_error": "True when a value present in bronze could not be converted to its type (row sent to quarantine).",
    "quarantine_reason": "Why the row could not be used (cast error).",
    "flag_column": "Boolean column of silver that stores the flag.",
    "flag_order": "Display order of the flag.",
    "flag_count": "Number of flags raised in the combination.",
    "rule_summary": "The rule of the flag in plain words.",
    "exam_requirement": "Exam requirement (Q3) the flag answers.",
    "description": "Plain-language description.",
    "dataset": "Source dataset (yellow trips or taxi zones).",
    "source_url": "URL the file was downloaded from.",
    "object_key": "Path of the file in the landing zone (raw/yellow/year=YYYY/month=MM/).",
    "source_etag": "ETag of the source file (detects a changed file).",
    "file_size_bytes": "Size of the downloaded file in bytes.",
    "sha256": "SHA-256 checksum of the downloaded file.",
    "schema_version": "Version of the source contract applied (v2024 or v2025).",
    "drift_report": "Columns added, missing or of another type than the contract expects.",
    "row_count_file": "Rows in the Parquet file.",
    "row_count_bronze": "Rows loaded into bronze (must equal the file).",
    "status": "pending, landed, loaded, failed or skipped_unchanged.",
    "forced": "True when the load was forced although the file had not changed.",
    "error_message": "Error of a failed attempt.",
}


def describe(name: str, documented: str) -> str:
    if documented:
        return documented
    if name in COMMON:
        return COMMON[name]
    if name.startswith("is_"):
        return f"True when the condition `{name[3:]}` holds (quality flag or attribute)."
    if name.startswith("sum_"):
        base = COMMON.get(name[4:], name[4:].replace("_", " "))
        return f"Sum over the grain of: {base[0].lower() + base[1:]} Additive; averages are computed at read time."
    if name.endswith("_trip_count"):
        return f"Trips with `{name[: -len('_trip_count')]}`."
    if name.endswith("_rows"):
        return f"Rows of the source month with `{name[: -len('_rows')]}`."
    if name.endswith("_total_amount"):
        return f"Total amount (USD) of the {name[: -len('_total_amount')]} trips."
    if name.endswith("_sk"):
        return f"Key of the `{name[: -len('_sk')]}` dimension (-1: unknown)."
    if name.endswith("_name") or name.endswith("_label"):
        return "Readable name of the code."
    if name.endswith("_at"):
        return "Timestamp."
    return ""


def column_table(columns: dict, catalog_columns: dict) -> list[str]:
    lines = ["| Column | Type | Description |", "|---|---|---|"]
    names = list(catalog_columns) or list(columns)
    for name in names:
        typ = catalog_columns.get(name, {}).get("type", "")
        documented = (columns.get(name, {}) or {}).get("description", "").replace("\n", " ").strip()
        desc = describe(name, documented)
        lines.append(f"| `{name}` | {typ.lower()} | {desc.replace('|', '/')} |")
    return lines


def main() -> None:
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads((DOCS / "catalog.json").read_text(encoding="utf-8"))
    models = [n for n in manifest["nodes"].values() if n["resource_type"] in ("model", "seed")]
    out = [
        "# Data dictionary",
        "",
        "Generated by `scripts/data_dictionary.py` from the dbt documentation "
        "(`docs/dbt_docs`): descriptions from the dbt YAML, types from the warehouse. "
        "Grain of the star schema: **one completed taxi trip** (`fct_trip`). Metric "
        "definitions are in `docs/metric_catalog.md` and summarised at the end.",
        "",
        "## Bronze (sources)",
        "",
    ]
    for key, source in sorted(manifest["sources"].items()):
        cat = catalog["sources"].get(key, {}).get("columns", {})
        out += [f"### `{source['schema']}.{source['name']}`", "",
                source.get("description", "").replace("\n", " ").strip(), ""]  # fmt: skip
        out += column_table(source.get("columns", {}), cat) + [""]
    done: set[str] = set()
    for title, prefix in LAYERS:
        group = [m for m in models if m["original_file_path"].startswith(prefix)
                 and m["unique_id"] not in done]  # fmt: skip
        if not group:
            continue
        out += [f"## {title}", ""]
        for m in sorted(group, key=lambda m: m["name"]):
            done.add(m["unique_id"])
            cat = catalog["nodes"].get(m["unique_id"], {}).get("columns", {})
            materialized = m["config"].get("materialized", "")
            out += [f"### `{m['schema']}.{m['name']}` ({materialized})", "",
                    m.get("description", "").replace("\n", " ").strip(), ""]  # fmt: skip
            out += column_table(m.get("columns", {}), cat) + [""]
    seeds = [m for m in models if m["resource_type"] == "seed"]
    if seeds:
        out += ["## Reference data (dbt seeds)", ""]
        for m in seeds:
            cat = catalog["nodes"].get(m["unique_id"], {}).get("columns", {})
            out += [f"### `{m['schema']}.{m['name']}`", "",
                    m.get("description", "").replace("\n", " ").strip(), ""]  # fmt: skip
            out += column_table(m.get("columns", {}), cat) + [""]
    out += EXTRA.strip("\n").splitlines() + ["", "## Governed metrics", ""]
    out += ["| Metric | Label | Type | Definition |", "|---|---|---|---|"]
    for metric in sorted(manifest.get("metrics", {}).values(), key=lambda m: m["name"]):
        desc = metric.get("description", "").replace("\n", " ").replace("|", "/").strip()
        out.append(
            f"| `{metric['name']}` | {metric.get('label', '')} | {metric['type']} | {desc} |"
        )
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    print(f"written {OUT.relative_to(ROOT)}: {len(out)} lines")


if __name__ == "__main__":
    main()
