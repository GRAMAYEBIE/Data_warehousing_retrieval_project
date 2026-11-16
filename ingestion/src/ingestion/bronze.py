"""Bronze load: replace one monthly partition with the content of a Parquet file."""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from psycopg import sql

from ingestion.contract import normalise

log = logging.getLogger(__name__)

# Source columns of bronze.yellow_trips_raw, in table order.
SOURCE_COLUMNS = [
    "vendorid",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
    "passenger_count",
    "trip_distance",
    "ratecodeid",
    "store_and_fwd_flag",
    "pulocationid",
    "dolocationid",
    "payment_type",
    "fare_amount",
    "extra",
    "mta_tax",
    "tip_amount",
    "tolls_amount",
    "improvement_surcharge",
    "total_amount",
    "congestion_surcharge",
    "airport_fee",
    "cbd_congestion_fee",
]
COPY_COLUMNS = [
    "source_month",
    "file_row_number",
    *SOURCE_COLUMNS,
    "extra_columns",
    "batch_id",
    "source_file",
    "schema_hash",
    "ingested_at",
]


class RowCountMismatch(Exception):
    """Bronze does not hold exactly the rows of the source file."""


def partition_name(month: date) -> str:
    return f"yellow_trips_raw_y{month:%Y}m{month:%m}"


def _batch_to_csv(
    batch: pa.RecordBatch,
    first_row_number: int,
    month: date,
    batch_id: UUID,
    source_file: str,
    schema_hash: str,
    ingested_at: datetime,
) -> bytes:
    """Render one Parquet batch as CSV in COPY_COLUMNS order."""
    n = batch.num_rows
    by_name = {normalise(name): batch.column(i) for i, name in enumerate(batch.schema.names)}

    arrays: list[pa.Array] = [
        pa.repeat(pa.scalar(month, type=pa.date32()), n),
        # 0-based position in the file: matches pyarrow/pandas row indexing.
        pa.array(range(first_row_number, first_row_number + n), type=pa.int64()),
    ]
    for name in SOURCE_COLUMNS:
        # A column the contract allows to be absent is stored as NULL.
        arrays.append(by_name[name] if name in by_name else pa.nulls(n, type=pa.float64()))

    unknown = sorted(name for name in by_name if name not in SOURCE_COLUMNS)
    if unknown:
        # Schema drift: keep values of columns the contract does not know yet.
        rows = pa.table({name: by_name[name] for name in unknown}).to_pylist()
        arrays.append(pa.array([json.dumps(r, default=str) for r in rows], type=pa.string()))
    else:
        arrays.append(pa.nulls(n, type=pa.string()))

    arrays.extend(
        [
            pa.repeat(pa.scalar(str(batch_id)), n),
            pa.repeat(pa.scalar(source_file), n),
            pa.repeat(pa.scalar(schema_hash), n),
            pa.repeat(pa.scalar(ingested_at.isoformat()), n),
        ]
    )

    buffer = io.BytesIO()
    pacsv.write_csv(
        pa.Table.from_arrays(arrays, names=COPY_COLUMNS),
        buffer,
        write_options=pacsv.WriteOptions(include_header=False),
    )
    return buffer.getvalue()


def replace_month(
    conn: psycopg.Connection,
    parquet_path: Path,
    month: date,
    batch_id: UUID,
    source_file: str,
    schema_hash: str,
    batch_rows: int,
) -> int:
    """Replace the month partition inside the caller's transaction.

    TRUNCATE + COPY run in one transaction: readers see either the previous
    content or the new one, and any failure leaves the previous content intact.
    Returns the number of rows now in the partition.
    """
    parquet_file = pq.ParquetFile(parquet_path)
    expected_rows = parquet_file.metadata.num_rows
    partition = sql.Identifier("bronze", partition_name(month))
    ingested_at = datetime.now(UTC)

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {} PARTITION OF bronze.yellow_trips_raw "
                "FOR VALUES IN ({})"
            ).format(partition, sql.Literal(month))
        )
        cur.execute(sql.SQL("TRUNCATE {}").format(partition))

        copy_sql = sql.SQL("COPY bronze.yellow_trips_raw ({}) FROM STDIN (FORMAT csv)").format(
            sql.SQL(", ").join(map(sql.Identifier, COPY_COLUMNS))
        )
        row_number = 0
        with cur.copy(copy_sql) as copy:
            for batch in parquet_file.iter_batches(batch_size=batch_rows):
                copy.write(
                    _batch_to_csv(
                        batch, row_number, month, batch_id, source_file, schema_hash, ingested_at
                    )
                )
                row_number += batch.num_rows
                log.info("bronze copy progress: %s / %s rows", row_number, expected_rows)

        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(partition))
        loaded_rows = cur.fetchone()[0]

    if loaded_rows != expected_rows:
        raise RowCountMismatch(f"bronze holds {loaded_rows} rows but the file has {expected_rows}")
    return loaded_rows
