"""Publication gate: copy approved gold tables to the analytics schema, atomically.

Superset and the AI assistant read only `analytics`. This step is the only writer of that
schema and it runs only after a green dbt build and a passing quality gate.

Why copies of gold and not views on gold: dbt replaces a gold table with
`DROP TABLE ... CASCADE`, which would silently drop any view built on it. A copy keeps
the published state independent from the next dbt build. The BI materialized views are
built on these copies (inside analytics), so dbt never touches them.

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


COMPLETE_MONTHS = "d.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver)"
DATE_ZONE_COLUMNS = """
    d.date_day, d.week_start, d.month_start, d.day_of_week, d.day_name, d.day_type,
    d.is_weekend, d.is_holiday, d.holiday_name,
    z.zone_name AS pickup_zone, z.borough AS pickup_borough,
    z.market_segment AS pickup_market_segment, z.is_airport AS is_pickup_airport"""
DATE_ZONE_JOINS = """
JOIN analytics.dim_date AS d ON a.pickup_date_sk = d.date_sk
JOIN analytics.dim_zone AS z ON a.pickup_zone_sk = z.zone_sk"""

# BI-ready materialized views over the published tables: dimensions already joined,
# complete months only, indexed. Superset datasets and the AI templates read these, so a
# chart is a scan of one indexed view instead of five joins on every request (the first
# version with joins in the datasets timed out at 120 s on the development machine).
# They are rebuilt in the publication transaction, after the tables they read.
BI_VIEWS: dict[str, tuple[str, list[str]]] = {
    "mv_trips_daily": (
        f"""
        SELECT a.*, {DATE_ZONE_COLUMNS},
            p.payment_type_name, r.rate_code_name, v.vendor_name
        FROM analytics.agg_trips_daily AS a {DATE_ZONE_JOINS}
        JOIN analytics.dim_payment_type AS p ON a.payment_type_sk = p.payment_type_sk
        JOIN analytics.dim_rate_code AS r ON a.rate_code_sk = r.rate_code_sk
        JOIN analytics.dim_vendor AS v ON a.vendor_sk = v.vendor_sk
        WHERE {COMPLETE_MONTHS}""",
        ["month_start", "date_day", "pickup_borough", "quality_status"],
    ),
    "mv_trips_hourly": (
        f"""
        SELECT a.*, {DATE_ZONE_COLUMNS}, sp.service_period_name, sp.is_peak
        FROM analytics.agg_trips_hourly AS a {DATE_ZONE_JOINS}
        JOIN analytics.dim_service_period AS sp ON a.service_period_sk = sp.service_period_sk
        WHERE {COMPLETE_MONTHS}""",
        ["month_start", "date_day", "pickup_hour", "pickup_borough"],
    ),
    "mv_routes_monthly": (
        """
        SELECT a.*, 'valid'::text AS quality_status,
            pz.zone_name AS pickup_zone, pz.borough AS pickup_borough,
            pz.market_segment AS pickup_market_segment, pz.is_airport AS is_pickup_airport,
            dz.zone_name AS dropoff_zone, dz.borough AS dropoff_borough,
            dz.market_segment AS dropoff_market_segment, dz.is_airport AS is_dropoff_airport,
            pz.zone_name || ' -> ' || dz.zone_name AS route,
            sp.service_period_name
        FROM analytics.agg_routes_monthly AS a
        JOIN analytics.dim_zone AS pz ON a.pickup_zone_sk = pz.zone_sk
        JOIN analytics.dim_zone AS dz ON a.dropoff_zone_sk = dz.zone_sk
        JOIN analytics.dim_service_period AS sp ON a.service_period_sk = sp.service_period_sk
        WHERE a.pickup_month IN (SELECT source_month FROM analytics.recon_bronze_silver)""",
        ["pickup_month", "pickup_borough", "route"],
    ),
    "mv_quality_daily": (
        f"""
        SELECT a.*, {DATE_ZONE_COLUMNS}, p.payment_type_name, v.vendor_name
        FROM analytics.agg_quality_daily AS a {DATE_ZONE_JOINS}
        JOIN analytics.dim_payment_type AS p ON a.payment_type_sk = p.payment_type_sk
        JOIN analytics.dim_vendor AS v ON a.vendor_sk = v.vendor_sk
        WHERE a.source_month IN (SELECT source_month FROM analytics.recon_bronze_silver)""",
        ["source_month", "date_day", "pickup_borough"],
    ),
}
LATEST = "(SELECT max(source_month) FROM analytics.recon_bronze_silver)"

# Analyses answering exam questions that need more than a grouped metric. Computed once
# per publication from the governed aggregates (valid trips only). Plain strings: the
# "{latest}" placeholder is replaced after the dict.
BI_VIEWS |= {
    # "Is revenue rising because there are more trips or higher fares?" Price-volume
    # decomposition of the change between consecutive complete months:
    #   volume effect = (trips - previous trips) x previous revenue per trip
    #   price effect  = (revenue per trip - previous revenue per trip) x trips
    # previous revenue + volume effect + price effect = revenue, exactly.
    "mv_revenue_bridge": (
        """
        WITH monthly AS (
            SELECT d.month_start,
                   sum(a.trip_count) FILTER (WHERE a.quality_status = 'valid')::numeric AS trips,
                   sum(a.sum_total_amount) FILTER (WHERE a.quality_status = 'valid') AS revenue
            FROM analytics.agg_trips_daily AS a
            JOIN analytics.dim_date AS d ON a.pickup_date_sk = d.date_sk
            WHERE d.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver)
            GROUP BY 1
        ), paired AS (
            SELECT month_start, trips, revenue, revenue / nullif(trips, 0) AS per_trip,
                   lag(month_start) OVER w AS previous_month, lag(trips) OVER w AS previous_trips,
                   lag(revenue) OVER w AS previous_revenue,
                   lag(revenue / nullif(trips, 0)) OVER w AS previous_per_trip
            FROM monthly WINDOW w AS (ORDER BY month_start)
        )
        SELECT p.month_start, p.previous_month,
               p.month_start = {latest} AS is_latest_month,
               s.step_order, s.step_order || '. ' || s.step AS step, round(s.amount, 2) AS amount
        FROM paired AS p
        CROSS JOIN LATERAL (VALUES
            (1, 'Revenue ' || to_char(p.previous_month, 'Mon YYYY'), p.previous_revenue),
            (2, 'Volume effect (number of trips)',
                (p.trips - p.previous_trips) * p.previous_per_trip),
            (3, 'Price effect (revenue per trip)', (p.per_trip - p.previous_per_trip) * p.trips)
        ) AS s (step_order, step, amount)
        WHERE p.previous_month IS NOT NULL""",
        ["month_start"],
    ),
    # "Which drop-off zones are growing fastest, and which are declining fastest?"
    # Latest complete month versus the month before; zones with at least 500 trips in the
    # previous month, so a small zone cannot top the list with a large percentage.
    "mv_dropoff_growth": (
        """
        WITH by_zone AS (
            SELECT a.dropoff_zone_sk,
                   sum(a.trip_count) FILTER (WHERE a.pickup_month = {latest}) AS latest,
                   sum(a.trip_count) FILTER (WHERE a.pickup_month = (
                       SELECT max(source_month) FROM analytics.recon_bronze_silver
                       WHERE source_month < {latest})) AS previous
            FROM analytics.agg_routes_monthly AS a
            GROUP BY 1
        )
        SELECT dz.zone_name AS dropoff_zone, dz.borough AS dropoff_borough,
               b.previous AS trips_previous_month, b.latest AS trips_latest_month,
               b.latest - b.previous AS trip_change,
               round(100.0 * (b.latest - b.previous) / b.previous, 2) AS trip_change_pct
        FROM by_zone AS b
        JOIN analytics.dim_zone AS dz ON b.dropoff_zone_sk = dz.zone_sk
        WHERE b.previous >= 500 AND b.latest IS NOT NULL""",
        ["trip_change_pct"],
    ),
    # "Which routes show the biggest gap between normal and current duration?"
    # Average duration of the latest month versus the earlier months (baseline), per route
    # and service period (at least 100 trips in both). The gap of each route is compared
    # with the gaps of all routes using a robust z-score, (gap - median) / (1.4826 x MAD),
    # so a few extreme routes do not hide the others and a general slowdown is not flagged
    # as a local disruption.
    "mv_route_duration_anomaly": (
        """
        WITH routes AS (
            SELECT a.pickup_zone_sk, a.dropoff_zone_sk, a.service_period_sk,
                   sum(a.trip_count)
                       FILTER (WHERE a.pickup_month = {latest}) AS current_trips,
                   sum(a.sum_duration_min)
                       FILTER (WHERE a.pickup_month = {latest}) AS current_minutes,
                   sum(a.trip_count)
                       FILTER (WHERE a.pickup_month < {latest}) AS baseline_trips,
                   sum(a.sum_duration_min)
                       FILTER (WHERE a.pickup_month < {latest}) AS baseline_minutes
            FROM analytics.agg_routes_monthly AS a
            WHERE a.pickup_month IN (SELECT source_month FROM analytics.recon_bronze_silver)
            GROUP BY 1, 2, 3
        ), gaps AS (
            SELECT *, current_minutes / current_trips AS current_avg,
                   baseline_minutes / baseline_trips AS baseline_avg,
                   100.0 * (current_minutes / current_trips - baseline_minutes / baseline_trips)
                       / nullif(baseline_minutes / baseline_trips, 0) AS gap_pct
            FROM routes
            WHERE current_trips >= 100 AND baseline_trips >= 100
        ), centre AS (
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_pct) AS median_gap FROM gaps
        ), spread AS (
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(g.gap_pct - c.median_gap)) AS mad
            FROM gaps AS g CROSS JOIN centre AS c
        )
        SELECT pz.zone_name || ' -> ' || dz.zone_name AS route, pz.borough AS pickup_borough,
               sp.service_period_name, g.baseline_trips, g.current_trips,
               round(g.baseline_avg, 1) AS baseline_avg_minutes,
               round(g.current_avg, 1) AS current_avg_minutes,
               round(g.gap_pct, 1) AS duration_gap_pct,
               round(((g.gap_pct - c.median_gap) / nullif(1.4826 * s.mad, 0))::numeric, 2)
                   AS robust_z
        FROM gaps AS g CROSS JOIN centre AS c CROSS JOIN spread AS s
        JOIN analytics.dim_zone AS pz ON g.pickup_zone_sk = pz.zone_sk
        JOIN analytics.dim_zone AS dz ON g.dropoff_zone_sk = dz.zone_sk
        JOIN analytics.dim_service_period AS sp ON g.service_period_sk = sp.service_period_sk""",
        ["robust_z", "pickup_borough"],
    ),
}
# "{latest}" in the analyses: the latest complete source month.
BI_VIEWS = {
    name: (query.replace("{latest}", LATEST), columns)
    for name, (query, columns) in BI_VIEWS.items()
}
BI_READERS = ("superset_reader", "ai_reader")


def drop_bi_views(cur) -> None:
    for name in BI_VIEWS:
        cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS analytics.{name}")


def create_bi_views(cur) -> dict[str, int]:
    counts = {}
    for name, (query, indexes) in BI_VIEWS.items():
        cur.execute(f"CREATE MATERIALIZED VIEW analytics.{name} AS {query}")
        for column in indexes:
            cur.execute(f"CREATE INDEX ON analytics.{name} ({column})")
        cur.execute(f"ANALYZE analytics.{name}")
        cur.execute(f"GRANT SELECT ON analytics.{name} TO {', '.join(BI_READERS)}")
        cur.execute(f"SELECT count(*) FROM analytics.{name}")
        counts[name] = cur.fetchone()[0]
    return counts


# Views read on every question or chart, loaded into PostgreSQL's memory after a
# publication (pg_prewarm), largest last so the smaller ones are certainly kept.
PREWARMED = ("mv_routes_monthly", "mv_trips_daily", "mv_trips_hourly")


def prewarm_bi_views(conn) -> dict[str, int]:
    """Best effort, after the commit: the publication never fails because of it."""
    loaded = {}
    try:
        with conn.cursor() as cur:
            for name in PREWARMED:
                cur.execute("SELECT util.pg_prewarm(%s::regclass)", (f"analytics.{name}",))
                loaded[name] = cur.fetchone()[0]  # blocks loaded
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - e.g. pg_prewarm not installed
        conn.rollback()
        log.warning("BI views not prewarmed: %s", exc)
    return loaded


def rebuild_bi_views(conn) -> dict[str, int]:
    """Rebuild the BI views alone (one transaction), e.g. after changing their definition."""
    with conn.cursor() as cur:
        drop_bi_views(cur)
        counts = create_bi_views(cur)
    conn.commit()
    prewarm_bi_views(conn)
    log.info("BI materialized views rebuilt: %s", counts)
    return counts


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
        # The BI views read the tables about to be swapped: drop them first, recreate them
        # at the end of this same transaction.
        drop_bi_views(cur)
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
        counts |= create_bi_views(cur)
        # The observability role reads the status and the reconciliation only, never the
        # business aggregates (infra/postgres/init/07_observability.sql).
        cur.execute(
            """
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metrics_reader') THEN
                    GRANT SELECT ON analytics.pipeline_status, analytics.recon_bronze_silver
                        TO metrics_reader;
                END IF;
            END $$
            """
        )
    conn.commit()
    log.info("published %s tables for run %s: %s", len(counts), run_id, counts)
    log.info("BI views loaded in memory (blocks): %s", prewarm_bi_views(conn))
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
