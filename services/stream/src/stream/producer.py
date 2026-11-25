"""Replay a monthly file as a stream of trips, in pickup order, faster than real time.

The TLC publishes a month about two months later; a stream lets the platform see the month
as it happens. Here the monthly file stands in for the trips' live feed: each trip is sent
when the simulated clock reaches its pickup time. With --speed 4320, a day passes in 20
seconds and the month in about ten minutes; --speed 0 sends as fast as possible.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from stream.contract import FIELDS, TOPIC, encode

log = logging.getLogger(__name__)
TLC_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{month}.parquet"


def fetch(month: str, cache: Path, base_url: str = TLC_URL) -> Path:
    """The monthly file, downloaded once into the cache."""
    path = cache / f"yellow_tripdata_{month}.parquet"
    if path.exists() and path.stat().st_size > 0:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    with httpx.stream("GET", base_url.format(month=month), follow_redirects=True,
                      timeout=httpx.Timeout(30.0, read=300.0)) as response:  # fmt: skip
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
    partial.rename(path)
    return path


def ordered_rows(path: Path):
    """(row number in the file, row) in pickup order; the row number is the trip's key, the
    same as in bronze (0-based position in the file)."""
    table = pq.read_table(path, columns=list(FIELDS.values()))
    table = table.append_column("_row", pa.array(range(table.num_rows), type=pa.int64()))
    table = table.sort_by([("tpep_pickup_datetime", "ascending"), ("_row", "ascending")])
    for batch in table.to_batches(max_chunksize=20_000):
        for row in batch.to_pylist():
            yield row.pop("_row"), row


def replay(producer, month: str, path: Path, speed: float, limit: int | None = None) -> int:
    """Send the trips of `month`; returns how many were sent."""
    start_sim = datetime.fromisoformat(f"{month}-01T00:00:00")
    start_wall = time.monotonic()
    sent, last_log = 0, start_wall
    for row_number, row in ordered_rows(path):
        pickup = row.get("tpep_pickup_datetime")
        if speed > 0 and isinstance(pickup, datetime) and pickup > start_sim:
            due = start_wall + (pickup - start_sim).total_seconds() / speed
            while (wait := due - time.monotonic()) > 0:  # deliveries are served meanwhile
                producer.poll(min(wait, 0.5))
        key, value = encode(month, row_number, row)
        while True:
            try:
                producer.produce(TOPIC, value=value, key=key)
                break
            except BufferError:  # local queue full: let it drain
                producer.poll(0.5)
        sent += 1
        if sent % 10_000 == 0:
            producer.poll(0)
        if time.monotonic() - last_log > 10:
            log.info("sent %d trips, simulated clock %s", sent, pickup)
            last_log = time.monotonic()
        if limit and sent >= limit:
            break
    producer.flush(60)
    log.info("replay of %s done: %d trips sent", month, sent)
    return sent
