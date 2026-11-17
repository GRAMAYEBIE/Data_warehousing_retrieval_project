"""Operational signals measured after the dbt build, before publication (exam Q5.4).

A signal with status 'fail' closes the publication gate: the analytics layer keeps the
previous state. 'warn' is reported but does not block. Thresholds are constants here so
they are reviewed with the code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

log = logging.getLogger(__name__)

# Thresholds (agreed values, documented in the README).
VOLUME_WARN_PCT = 20.0  # |change vs previous month| above this: warn
VOLUME_FAIL_PCT = 50.0  # above this: fail (likely a truncated or wrong file)
REJECTED_WARN_PCT = 10.0  # suspicious + invalid share of silver rows
REJECTED_FAIL_PCT = 20.0
LATE_WARN_PCT = 0.1  # cross-month rows share
FRESHNESS_WARN_DAYS = 45  # same as the dbt source freshness (warn)


@dataclass
class Signal:
    name: str
    value: float | None
    unit: str
    threshold: str
    status: str  # ok | warn | fail
    details: dict = field(default_factory=dict)


def volume_signal(rows: int | None, previous_rows: int | None) -> Signal:
    threshold = f"|change| warn > {VOLUME_WARN_PCT}%, fail > {VOLUME_FAIL_PCT}%"
    if not rows:
        return Signal(
            "volume_change_vs_prior_month",
            None,
            "%",
            threshold,
            "fail",
            {"reason": "no row for this month in bronze"},
        )
    if not previous_rows:
        return Signal(
            "volume_change_vs_prior_month",
            None,
            "%",
            threshold,
            "ok",
            {"rows": rows, "reason": "no previous month loaded"},
        )
    change = round(100.0 * (rows - previous_rows) / previous_rows, 2)
    status = (
        "fail"
        if abs(change) > VOLUME_FAIL_PCT
        else "warn"
        if abs(change) > VOLUME_WARN_PCT
        else "ok"
    )
    return Signal(
        "volume_change_vs_prior_month",
        change,
        "%",
        threshold,
        status,
        {"rows": rows, "previous_rows": previous_rows},
    )


def rejected_signal(silver_rows: int, suspicious: int, invalid: int) -> Signal:
    threshold = f"warn > {REJECTED_WARN_PCT}%, fail > {REJECTED_FAIL_PCT}%"
    rate = round(100.0 * (suspicious + invalid) / silver_rows, 2) if silver_rows else None
    status = (
        "fail"
        if rate is None or rate > REJECTED_FAIL_PCT
        else "warn"
        if rate > REJECTED_WARN_PCT
        else "ok"
    )
    return Signal(
        "rejected_row_rate",
        rate,
        "%",
        threshold,
        status,
        {"silver_rows": silver_rows, "suspicious": suspicious, "invalid": invalid},
    )


def late_data_signal(silver_rows: int, cross_month_rows: int) -> Signal:
    rate = round(100.0 * cross_month_rows / silver_rows, 4) if silver_rows else 0.0
    status = "warn" if rate > LATE_WARN_PCT else "ok"
    return Signal(
        "late_data_rate",
        rate,
        "%",
        f"warn > {LATE_WARN_PCT}%",
        status,
        {"cross_month_rows": cross_month_rows},
    )


def freshness_signal(last_load: datetime | None, now: datetime) -> Signal:
    threshold = f"warn > {FRESHNESS_WARN_DAYS} days since the last successful load"
    if last_load is None:
        return Signal(
            "freshness_days", None, "days", threshold, "warn", {"reason": "no successful load"}
        )
    # The database returns timestamptz; a naive value is taken as UTC so both sides compare.
    last_load, now = (
        value if value.tzinfo else value.replace(tzinfo=UTC) for value in (last_load, now)
    )
    days = round((now - last_load).total_seconds() / 86400, 2)
    return Signal(
        "freshness_days",
        days,
        "days",
        threshold,
        "warn" if days > FRESHNESS_WARN_DAYS else "ok",
        {"last_load": last_load.isoformat()},
    )


def test_pass_signal(passed: int, total: int) -> Signal:
    if total == 0:
        return Signal(
            "dbt_test_pass_rate",
            None,
            "%",
            "fail < 100%",
            "warn",
            {"reason": "no test result recorded for this run"},
        )
    rate = round(100.0 * passed / total, 2)
    return Signal(
        "dbt_test_pass_rate",
        rate,
        "%",
        "fail < 100%",
        "ok" if passed == total else "fail",
        {"passed": passed, "total": total},
    )


def measure(conn, run_id: str, month: date, now: datetime) -> list[Signal]:
    """Measure every signal for the run's month from gold and ops."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bronze_rows, silver_rows, suspicious_rows, invalid_rows, cross_month_rows
            FROM gold.recon_bronze_silver WHERE source_month = %s
            """,
            (month,),
        )
        current = cur.fetchone()
        cur.execute(
            "SELECT bronze_rows FROM gold.recon_bronze_silver "
            "WHERE source_month = (%s::date - interval '1 month')::date",
            (month,),
        )
        previous = cur.fetchone()
        cur.execute(
            "SELECT max(finished_at) FROM ops.ingestion_manifest "
            "WHERE dataset = 'yellow' AND status = 'loaded'"
        )
        last_load = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FILTER (WHERE status = 'pass'), count(*) "
            "FROM ops.dbt_test_results WHERE run_id = %s",
            (run_id,),
        )
        passed, total = cur.fetchone()

    if current is None:
        bronze_rows = silver_rows = suspicious = invalid = cross_month = 0
    else:
        bronze_rows, silver_rows, suspicious, invalid, cross_month = current
    signals = [
        freshness_signal(last_load, now),
        volume_signal(bronze_rows, previous[0] if previous else None),
        rejected_signal(silver_rows, suspicious or 0, invalid or 0),
        late_data_signal(silver_rows, cross_month or 0),
        test_pass_signal(passed, total),
    ]
    return signals


def record(conn, run_id: str, month: date, signals: list[Signal]) -> None:
    with conn.cursor() as cur:
        for s in signals:
            cur.execute(
                """
                INSERT INTO ops.pipeline_signals
                    (run_id, source_month, signal_name, signal_value, unit, threshold,
                     status, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, signal_name) DO UPDATE SET
                    signal_value = EXCLUDED.signal_value, status = EXCLUDED.status,
                    details = EXCLUDED.details, measured_at = now()
                """,
                (
                    run_id,
                    month,
                    s.name,
                    s.value,
                    s.unit,
                    s.threshold,
                    s.status,
                    json.dumps(s.details, default=str),
                ),
            )
    conn.commit()
    for s in signals:
        log.info("signal %-30s %-8s %s %s (%s)", s.name, s.status, s.value, s.unit, s.threshold)
