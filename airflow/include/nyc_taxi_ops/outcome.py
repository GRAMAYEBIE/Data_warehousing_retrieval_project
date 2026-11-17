"""Run bookkeeping and the outcome notification of the monthly pipeline."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import date

log = logging.getLogger(__name__)


def start_run(conn, run_id: str, dag_id: str, month: date, forced: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.pipeline_runs (run_id, dag_id, source_month, forced, status)
            VALUES (%s, %s, %s, %s, 'running')
            ON CONFLICT (run_id) DO UPDATE SET status = 'running', finished_at = NULL,
                message = NULL
            """,
            (run_id, dag_id, month, forced),
        )
    conn.commit()


def finish_run(conn, run_id: str) -> dict:
    """Decide the outcome from the warehouse state, record it, and return a summary.

    published   : a publication exists for this run
    nothing_new : every loaded batch was already published (the run had nothing to do)
    failed      : anything else (a step failed or the quality gate refused publication)
    """
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ops.publications WHERE run_id = %s", (run_id,))
        published = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT status, message, source_month::text FROM ops.pipeline_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        current_status, message, month = row if row else (None, None, None)
        cur.execute(
            "SELECT signal_name, status, signal_value, unit FROM ops.pipeline_signals "
            "WHERE run_id = %s ORDER BY signal_name",
            (run_id,),
        )
        signals = [
            {"name": n, "status": s, "value": float(v) if v is not None else None, "unit": u}
            for n, s, v, u in cur.fetchall()
        ]
        if published:
            status = "published"
        elif current_status == "nothing_new":
            status = "nothing_new"
        else:
            status = "failed"
        cur.execute(
            "UPDATE ops.pipeline_runs SET status = %s, published = %s, finished_at = now() "
            "WHERE run_id = %s",
            (status, published, run_id),
        )
    conn.commit()
    return {
        "run_id": run_id,
        "source_month": month,
        "status": status,
        "published": published,
        "message": message,
        "signals": signals,
    }


def mark(conn, run_id: str, status: str, message: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ops.pipeline_runs SET status = %s, message = %s WHERE run_id = %s",
            (status, message, run_id),
        )
    conn.commit()


def notify(summary: dict) -> None:
    """Log the outcome; also POST it to NOTIFY_WEBHOOK_URL when that variable is set."""
    level = logging.ERROR if summary.get("status") == "failed" else logging.INFO
    log.log(level, "pipeline outcome: %s", json.dumps(summary, default=str))
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return
    body = json.dumps({"text": f"NYC Taxi Insight Hub: {summary}"}, default=str).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            log.info("webhook notified (HTTP %s)", response.status)
    except Exception:  # a notification failure must not fail the pipeline
        log.exception("webhook notification failed")
