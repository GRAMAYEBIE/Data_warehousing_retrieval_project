"""Publication gate: copy approved gold tables to the analytics schema, atomically.

Superset and the AI assistant read only `analytics`. This step is the only writer of that
schema and it runs only after a green dbt build and a passing quality gate.

Why copies and not materialized views: dbt replaces a gold table with
`DROP TABLE ... CASCADE`, which would silently drop any view built on it. A copy keeps
the published state independent from the next dbt build.

Each table is rebuilt as `<name>__next`, then the old table is dropped and the new one
renamed, all in ONE transaction: readers see the complete previous state or the complete
new one, never a mix.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishedTable:
    name: str
    source: str  # schema-qualified relation copied as it is
    description: str
    indexes: Sequence[str] = ()


PUBLISHED_TABLES: tuple[PublishedTable, ...] = (
    PublishedTable(
        "agg_trips_daily",
        "gold.agg_trips_daily",
        "Daily additive trip aggregate by pickup zone, payment, rate code, vendor and status.",
        ("pickup_date_sk", "pickup_zone_sk"),
    ),
    PublishedTable(
        "agg_trips_hourly",
        "gold.agg_trips_hourly",
        "Hourly additive trip aggregate for demand rhythm and trips per active hour.",
        ("pickup_date_sk, pickup_hour", "pickup_zone_sk"),
    ),
    PublishedTable(
        "agg_routes_monthly",
        "gold.agg_routes_monthly",
        "Monthly route aggregate (pickup zone to dropoff zone), valid trips only.",
        ("pickup_month", "pickup_zone_sk, dropoff_zone_sk"),
    ),
    PublishedTable(
        "agg_quality_daily",
        "gold.agg_quality_daily",
        "Data-quality aggregate: trips per status and per flag.",
        ("source_month", "pickup_date_sk"),
    ),
    PublishedTable(
        "recon_bronze_silver",
        "gold.recon_bronze_silver",
        "Bronze to silver reconciliation per source file month.",
    ),
    PublishedTable("dim_date", "gold.dim_date", "Calendar day, weekend and public holidays."),
    PublishedTable("dim_time", "gold.dim_time", "Minute of the day, hour and day part."),
    PublishedTable("dim_zone", "gold.dim_zone", "TLC taxi zones, borough, airport, segment."),
    PublishedTable("dim_payment_type", "gold.dim_payment_type", "TLC payment types."),
    PublishedTable("dim_rate_code", "gold.dim_rate_code", "TLC rate codes."),
    PublishedTable("dim_vendor", "gold.dim_vendor", "Trip data vendors."),
    PublishedTable("dim_service_period", "gold.dim_service_period", "Peak and off-peak periods."),
    PublishedTable("dim_trip_quality", "gold.dim_trip_quality", "Combinations of quality flags."),
    PublishedTable(
        "quality_flag_catalog", "gold.quality_flag_catalog", "Data-quality flag catalogue."
    ),
)


# Operational tables copied to analytics at each publication (no secret, no free text
# from the source: only statuses, counts, checksums and messages written by the platform).
OPS_SNAPSHOTS: dict[str, str] = {
    "pipeline_runs": "SELECT * FROM ops.pipeline_runs",
    "pipeline_signals": "SELECT * FROM ops.pipeline_signals",
    "publications": "SELECT publication_id, run_id, published_at, batches FROM ops.publications",
    "ingestion_batches": (
        "SELECT batch_id, dataset, source_month, status, forced, schema_version, schema_hash, "
        "row_count_file, row_count_bronze, file_size_bytes, sha256, error_message, "
        "started_at, finished_at FROM ops.ingestion_manifest"
    ),
}


class GateClosed(Exception):
    """The quality gate refuses publication."""


def check_gate(conn, run_id: str) -> dict:
    """Last checks before publishing; raise GateClosed with the reasons when one fails.

    1. Every loaded month reconciles: no unexplained row or amount between bronze and silver.
    2. No operational signal of this run has status 'fail'.
    3. No dbt test recorded for this run failed.
    """
    reasons: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_month::text, unexplained_rows, unexplained_amount
            FROM gold.recon_bronze_silver
            WHERE unexplained_rows <> 0 OR abs(unexplained_amount) > 0.01
            """
        )
        for month, rows, amount in cur.fetchall():
            reasons.append(f"reconciliation gap in {month}: {rows} rows, {amount} USD")

        cur.execute(
            "SELECT signal_name, signal_value FROM ops.pipeline_signals "
            "WHERE run_id = %s AND status = 'fail'",
            (run_id,),
        )
        for name, value in cur.fetchall():
            reasons.append(f"signal {name} failed (value {value})")

        cur.execute(
            "SELECT count(*) FROM ops.dbt_test_results "
            "WHERE run_id = %s AND status IN ('fail', 'error')",
            (run_id,),
        )
        failed_tests = cur.fetchone()[0]
        if failed_tests:
            reasons.append(f"{failed_tests} dbt test(s) failed")

    if reasons:
        raise GateClosed("; ".join(reasons))
    log.info("quality gate open for run %s", run_id)
    return {"run_id": run_id, "gate": "open"}


def publish(conn, run_id: str) -> dict:
    """Swap every published table in one transaction and record the publication."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '60s'")
        for table in PUBLISHED_TABLES:
            next_name = f"{table.name}__next"
            cur.execute(f"DROP TABLE IF EXISTS analytics.{next_name}")
            cur.execute(f"CREATE TABLE analytics.{next_name} AS SELECT * FROM {table.source}")
            for columns in table.indexes:
                # Unnamed: PostgreSQL picks a free name, so successive publications never clash.
                cur.execute(f"CREATE INDEX ON analytics.{next_name} ({columns})")
            cur.execute(f"DROP TABLE IF EXISTS analytics.{table.name}")
            cur.execute(f"ALTER TABLE analytics.{next_name} RENAME TO {table.name}")
            comment = f"{table.description} Published by run {run_id} from {table.source}."
            quoted = comment.replace("'", "''")
            cur.execute(f"COMMENT ON TABLE analytics.{table.name} IS '{quoted}'")
            cur.execute(f"SELECT count(*) FROM analytics.{table.name}")
            counts[table.name] = cur.fetchone()[0]

        # Status table read by the "last refreshed" tile and by the AI provenance.
        # Coverage counts valid trips only: invalid rows can carry aberrant dates.
        cur.execute("DROP TABLE IF EXISTS analytics.pipeline_status")
        cur.execute(
            """
            CREATE TABLE analytics.pipeline_status AS
            WITH valid_days AS (
                SELECT d.date_day
                FROM gold.agg_trips_daily AS a
                JOIN gold.dim_date AS d ON a.pickup_date_sk = d.date_sk
                WHERE a.quality_status = 'valid'
            )
            SELECT
                now() AS published_at,
                %s::text AS run_id,
                (SELECT min(date_day) FROM valid_days) AS first_pickup_date,
                (SELECT max(date_day) FROM valid_days) AS last_pickup_date,
                (SELECT min(source_month) FROM gold.recon_bronze_silver) AS first_source_month,
                (SELECT max(source_month) FROM gold.recon_bronze_silver) AS latest_source_month,
                (SELECT count(*) FROM gold.recon_bronze_silver) AS source_months_loaded,
                (SELECT max(finished_at) FROM ops.ingestion_manifest
                   WHERE dataset = 'yellow' AND status = 'loaded') AS last_ingestion_at
            """,
            (run_id,),
        )

        cur.execute(
            """
            SELECT jsonb_object_agg(source_month::text, batch_id::text)
            FROM gold.recon_bronze_silver
            """
        )
        batches = cur.fetchone()[0] or {}
        cur.execute(
            "INSERT INTO ops.publications (run_id, tables, batches) VALUES (%s, %s, %s)",
            (run_id, json.dumps(counts), json.dumps(batches)),
        )

        # Operational history for Dashboard 5 and the data-quality status shown to users,
        # published in the same transaction (it includes the publication just recorded).
        for name, query in OPS_SNAPSHOTS.items():
            cur.execute(f"DROP TABLE IF EXISTS analytics.{name}")
            cur.execute(f"CREATE TABLE analytics.{name} AS {query}")
    conn.commit()
    log.info("published %s tables for run %s: %s", len(counts), run_id, counts)
    return {"tables": counts, "batches": batches}


def latest_published_batches(conn) -> dict:
    """Batches contained in the last publication ({} when nothing was published yet)."""
    with conn.cursor() as cur:
        cur.execute("SELECT batches FROM ops.publications ORDER BY published_at DESC LIMIT 1")
        row = cur.fetchone()
    if not row:
        return {}
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def latest_loaded_batches(conn) -> dict:
    """Latest loaded batch per source month according to the ingestion manifest."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (source_month) source_month::text, batch_id::text
            FROM ops.ingestion_manifest
            WHERE dataset = 'yellow' AND status = 'loaded'
            ORDER BY source_month, finished_at DESC
            """
        )
        return dict(cur.fetchall())
