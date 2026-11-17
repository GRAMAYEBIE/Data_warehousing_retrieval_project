"""Ingestion manifest: one row per attempt in ops.ingestion_manifest."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

FINAL_STATUSES = {"loaded", "failed", "skipped_unchanged"}


def start(
    conn: psycopg.Connection,
    batch_id: UUID,
    dataset: str,
    source_month: date | None,
    source_url: str,
    forced: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO ops.ingestion_manifest
            (batch_id, dataset, source_month, source_url, status, forced)
        VALUES (%s, %s, %s, %s, 'pending', %s)
        """,
        (batch_id, dataset, source_month, source_url, forced),
    )


def update(conn: psycopg.Connection, batch_id: UUID, **fields: Any) -> None:
    """Update manifest columns; a final status also stamps finished_at."""
    if "drift_report" in fields and fields["drift_report"] is not None:
        fields["drift_report"] = Jsonb(fields["drift_report"])
    assignments = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in fields]
    if fields.get("status") in FINAL_STATUSES:
        # clock_timestamp(), not now(): now() is frozen at the start of the load transaction.
        assignments.append(sql.SQL("finished_at = clock_timestamp()"))
    query = sql.SQL("UPDATE ops.ingestion_manifest SET {} WHERE batch_id = {}").format(
        sql.SQL(", ").join(assignments), sql.Placeholder("batch_id")
    )
    conn.execute(query, {**fields, "batch_id": batch_id})


def last_loaded(
    conn: psycopg.Connection, dataset: str, source_month: date | None
) -> dict[str, Any] | None:
    """Most recent successful load of this dataset/month, if any."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM ops.ingestion_manifest
            WHERE dataset = %s
              AND source_month IS NOT DISTINCT FROM %s
              AND status = 'loaded'
            ORDER BY finished_at DESC
            LIMIT 1
            """,
            (dataset, source_month),
        )
        return cur.fetchone()


def latest_batch(
    conn: psycopg.Connection, dataset: str, source_month: date | None
) -> dict[str, Any] | None:
    """Most recent batch of this dataset/month that reached the landing zone.

    Status 'landed' means the file is stored and validated but not yet in bronze;
    'loaded' means bronze holds it. Attempts that were skipped or failed are ignored.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT * FROM ops.ingestion_manifest
            WHERE dataset = %s
              AND source_month IS NOT DISTINCT FROM %s
              AND status IN ('landed', 'loaded')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (dataset, source_month),
        )
        return cur.fetchone()


def get(conn: psycopg.Connection, batch_id: UUID) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM ops.ingestion_manifest WHERE batch_id = %s", (batch_id,))
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"no manifest row for batch {batch_id}")
    return row
