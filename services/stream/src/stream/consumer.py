"""Kafka -> PostgreSQL: the provisional trips of the month, checked against the contract.

Delivery is at least once, rows exactly once:
- messages are read in batches and written in one transaction (valid trips with
  INSERT ... ON CONFLICT DO NOTHING on the trip key, rejects with their reason);
- the offsets are committed to Kafka only after the transaction: a crash in between
  re-delivers the batch, and the key makes the second write a no-op.
A message that breaks the contract goes to the dead-letter topic and to
stream.yellow_trips_rejects; it never stops the stream.
"""

from __future__ import annotations

import logging
import time
from dataclasses import astuple

from stream.contract import DEAD_LETTERS, Rejected, Trip, decode

log = logging.getLogger(__name__)
COLUMNS = (
    "source_month, file_row_number, vendor_id, pickup_ts, dropoff_ts, pu_location_id, "
    "do_location_id, passenger_count, trip_distance, payment_type, fare_amount, tip_amount, "
    "total_amount, kafka_partition, kafka_offset"
)


def split(messages) -> tuple[list[tuple], list[tuple]]:
    """(rows, rejects) of a batch of Kafka messages (objects with value(), partition(),
    offset()); a message with a transport error is a reject too."""
    rows, rejects = [], []
    for m in messages:
        if m.error():
            rejects.append((None, m.partition() or 0, m.offset() or 0, f"kafka: {m.error()}", ""))
            continue
        try:
            trip: Trip = decode(m.value())
        except Rejected as exc:
            text = (m.value() or b"").decode("utf-8", "replace")[:2000]
            rejects.append((None, m.partition(), m.offset(), str(exc), text))
            continue
        rows.append((*astuple(trip), m.partition(), m.offset()))
    return rows, rejects


def write(conn, rows: list[tuple], rejects: list[tuple]) -> int:
    """One transaction: the trips (duplicates ignored) and the rejects. Returns the number
    of new trips."""
    with conn.transaction(), conn.cursor() as cur:
        inserted = 0
        if rows:
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS incoming "
                "(LIKE stream.yellow_trips INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
            )
            with cur.copy(f"COPY incoming ({COLUMNS}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            cur.execute(
                f"INSERT INTO stream.yellow_trips ({COLUMNS}) SELECT {COLUMNS} FROM incoming "
                "ON CONFLICT (source_month, file_row_number) DO NOTHING"
            )
            inserted = cur.rowcount
        if rejects:
            cur.executemany(
                "INSERT INTO stream.yellow_trips_rejects "
                "(source_month, kafka_partition, kafka_offset, reason, message) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                rejects,
            )
    return inserted


def run(consumer, producer, conn, batch: int = 5000, idle_log_s: float = 60) -> None:
    """Consume until stopped. `producer` sends the rejects to the dead-letter topic."""
    received = stored = rejected = 0
    last_log = time.monotonic()
    while True:
        messages = consumer.consume(num_messages=batch, timeout=1.0)
        if messages:
            rows, rejects = split(messages)
            stored += write(conn, rows, rejects)
            for _, partition, offset, reason, text in rejects:
                producer.produce(DEAD_LETTERS, value=text.encode(), key=f"{partition}:{offset}",
                                 headers={"reason": reason[:200]})  # fmt: skip
            producer.poll(0)
            consumer.commit(asynchronous=False)  # after the database: at least once
            received += len(messages)
            rejected += len(rejects)
        if time.monotonic() - last_log > (10 if messages else idle_log_s):
            log.info("received %d, stored %d new trips, rejected %d", received, stored, rejected)
            last_log = time.monotonic()
