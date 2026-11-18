"""Database access: read as ai_reader (read-only, 10 s), audit as ai_audit_writer."""

from __future__ import annotations

import json
import time

import psycopg

from assistant.config import Settings


class Store:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def reader(self) -> psycopg.Connection:
        # The role itself is read-only with statement_timeout = 10 s (infra/postgres/init);
        # the session settings repeat it so a misconfigured role cannot widen it.
        return psycopg.connect(
            host=self.s.db_host,
            dbname=self.s.db_name,
            user="ai_reader",
            password=self.s.reader_password,
            options="-c default_transaction_read_only=on -c statement_timeout=10000",
            autocommit=True,
        )

    def query(self, sql: str, params: dict) -> tuple[list[str], list[tuple], int]:
        start = time.monotonic()
        with self.reader() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [c.name for c in cur.description]
            rows = cur.fetchall()
        return columns, rows, int((time.monotonic() - start) * 1000)

    def valid_trip_rate(self, months: list[str]) -> float | None:
        sql = """
            SELECT sum(a.trip_count) FILTER (WHERE a.quality_status = 'valid')::float
                   / nullif(sum(a.trip_count), 0)
            FROM analytics.agg_trips_daily AS a
            JOIN analytics.dim_date AS d ON a.pickup_date_sk = d.date_sk
            WHERE d.month_start = ANY(%(m)s::date[])
        """
        with self.reader() as conn, conn.cursor() as cur:
            cur.execute(sql, {"m": [f"{m}-01" for m in months]})
            value = cur.fetchone()[0]
        return None if value is None else round(value, 4)

    def audit(self, **event) -> None:
        """Best effort: an audit failure never breaks an answer, it is printed instead."""
        try:
            with psycopg.connect(
                host=self.s.db_host,
                dbname=self.s.db_name,
                user="ai_audit_writer",
                password=self.s.audit_password,
                autocommit=True,
            ) as conn:
                conn.execute(
                    """
                    INSERT INTO ops.ai_audit_log
                        (session_id, question, prompt_variant, model, plan, verdict, reasons,
                         rendered_sql, row_count, narrative_check, duration_ms)
                    VALUES (%(session_id)s, %(question)s, %(prompt_variant)s, %(model)s,
                            %(plan)s, %(verdict)s, %(reasons)s, %(rendered_sql)s,
                            %(row_count)s, %(narrative_check)s, %(duration_ms)s)
                    """,
                    {
                        "session_id": event.get("session_id", ""),
                        "question": event.get("question", ""),
                        "prompt_variant": event.get("prompt_variant"),
                        "model": event.get("model"),
                        "plan": json.dumps(event.get("plan")) if event.get("plan") else None,
                        "verdict": event["verdict"],
                        "reasons": json.dumps(event.get("reasons") or []),
                        "rendered_sql": event.get("rendered_sql"),
                        "row_count": event.get("row_count"),
                        "narrative_check": event.get("narrative_check"),
                        "duration_ms": event.get("duration_ms"),
                    },
                )
        except Exception as exc:  # noqa: BLE001 - auditing must not break the answer
            print(f"audit log write failed: {exc}")
