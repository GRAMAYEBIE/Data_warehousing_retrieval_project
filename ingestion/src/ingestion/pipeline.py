"""Ingestion pipelines: source -> landing zone -> bronze, with a manifest row per attempt."""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg

from ingestion import bronze, manifest, source
from ingestion.config import Settings, manifest_object_key, yellow_object_key
from ingestion.contract import check_schema, load_contract, schema_hash
from ingestion.storage import LandingZone

log = logging.getLogger(__name__)

ZONE_COLUMNS = ["LocationID", "Borough", "Zone", "service_zone"]
ZONES_OBJECT_KEY = "raw/taxi_zone/taxi_zone_lookup.csv"


class ContractViolation(Exception):
    """The file schema breaks the source contract in a blocking way."""


def _write_manifest_object(
    conn: psycopg.Connection, landing: LandingZone, batch_id: UUID, month: date | None
) -> None:
    """Copy the manifest row to the landing zone. Best effort: the table is the reference."""
    try:
        row = manifest.get(conn, batch_id)
        key = manifest_object_key(
            row["dataset"],
            str(batch_id),
            month.year if month else None,
            month.month if month else None,
        )
        landing.put_json(key, row)
    except Exception:
        log.exception("could not write the manifest object for batch %s", batch_id)


class NothingToLoad(Exception):
    """No validated file of this month is in the landing zone."""


def check_yellow(settings: Settings, month: date) -> source.SourceInfo:
    """Check that the monthly file is published. Raises SourceNotAvailable otherwise."""
    info = source.head(settings.yellow_url(month.year, month.month))
    log.info("source available: %s (%s bytes, ETag %s)", info.url, info.size, info.etag)
    return info


def ingest_yellow(settings: Settings, month: date, force: bool = False) -> str:
    """Land then load one monthly file (the command-line path). Returns the final status."""
    status = land_yellow(settings, month, force)
    loaded = load_yellow(settings, month)
    return "skipped_unchanged" if status == "skipped_unchanged" and not loaded else "loaded"


def land_yellow(settings: Settings, month: date, force: bool = False) -> str:
    """Fetch, validate and store one monthly Yellow Taxi file in the landing zone.

    Returns 'landed' or 'skipped_unchanged'. Safe to re-run: an unchanged source file
    is skipped; a changed or forced one replaces the landing object (same key) and
    creates a new batch that load_yellow will put in bronze.
    """
    batch_id = uuid4()
    url = settings.yellow_url(month.year, month.month)
    key = yellow_object_key(month.year, month.month)
    file_name = key.rsplit("/", 1)[-1]
    landing = LandingZone(settings)

    with psycopg.connect(autocommit=True) as meta:
        manifest.start(meta, batch_id, "yellow", month, url, force)
        log.info(
            "batch %s started: month=%s force=%s url=%s", batch_id, f"{month:%Y-%m}", force, url
        )
        try:
            landing.ensure_bucket()

            # 1. Check the source.
            info = source.head(url)
            manifest.update(
                meta, batch_id, source_etag=info.etag, file_size_bytes=info.size, object_key=key
            )

            # 2. Cheap idempotency check: same ETag and size as the last landed file.
            previous = manifest.latest_batch(meta, "yellow", month)
            if (
                previous
                and not force
                and info.etag
                and previous["source_etag"] == info.etag
                and previous["file_size_bytes"] == info.size
                and landing.object_size(key) == info.size
            ):
                log.info("source unchanged (ETag %s): nothing to do", info.etag)
                manifest.update(
                    meta,
                    batch_id,
                    status="skipped_unchanged",
                    sha256=previous["sha256"],
                    schema_hash=previous["schema_hash"],
                    schema_version=previous["schema_version"],
                    row_count_file=previous["row_count_file"],
                    row_count_bronze=previous["row_count_bronze"],
                )
                return "skipped_unchanged"

            with tempfile.TemporaryDirectory() as tmp:
                # 3. Download and validate the file (type, size, checksum).
                local = source.download(url, Path(tmp) / file_name)
                parquet_file = source.validate_parquet(local.path, info.size)
                file_rows = parquet_file.metadata.num_rows
                file_schema = parquet_file.schema_arrow
                file_hash = schema_hash(file_schema)
                manifest.update(
                    meta,
                    batch_id,
                    file_size_bytes=local.size,
                    sha256=local.sha256,
                    schema_hash=file_hash,
                    row_count_file=file_rows,
                )
                log.info(
                    "downloaded %s bytes, sha256=%s, rows=%s", local.size, local.sha256, file_rows
                )

                # 4. Strong idempotency check: identical content.
                if previous and not force and previous["sha256"] == local.sha256:
                    log.info("content unchanged (same SHA-256): nothing to do")
                    manifest.update(
                        meta,
                        batch_id,
                        status="skipped_unchanged",
                        schema_version=previous["schema_version"],
                        row_count_bronze=previous["row_count_bronze"],
                    )
                    return "skipped_unchanged"

                # 5. Schema contract and drift detection.
                contract = load_contract(settings.contracts_dir, "yellow", f"{month:%Y-%m}")
                drift = check_schema(file_schema, contract)
                manifest.update(
                    meta,
                    batch_id,
                    schema_version=contract.version,
                    drift_report=drift.to_dict() if drift.has_drift else None,
                )
                if drift.unknown_columns:
                    log.warning(
                        "schema drift: unknown columns %s kept in extra_columns",
                        drift.unknown_columns,
                    )
                if drift.missing_optional:
                    log.warning("schema drift: optional columns absent %s", drift.missing_optional)
                if drift.blocking:
                    raise ContractViolation(
                        f"contract {contract.version} violated: "
                        f"missing={drift.missing_required} types={drift.type_mismatches}"
                    )

                # 6. Land the raw file (same key on every run).
                landing.upload_file(local.path, key, local.sha256)
                manifest.update(meta, batch_id, status="landed")
                log.info("landed s3://%s/%s", landing.bucket, key)
                return "landed"
        except Exception as exc:
            log.error("batch %s failed: %s", batch_id, exc)
            manifest.update(
                meta, batch_id, status="failed", error_message=f"{type(exc).__name__}: {exc}"
            )
            raise
        finally:
            _write_manifest_object(meta, landing, batch_id, month)


def load_yellow(settings: Settings, month: date) -> bool:
    """Load the latest landed file of the month into its bronze partition.

    Reads the file from the landing zone, never from the source, and checks its
    SHA-256 against the manifest before loading. Returns True when bronze was
    replaced, False when the latest landed batch is already in bronze.
    """
    landing = LandingZone(settings)
    with psycopg.connect(autocommit=True) as meta, psycopg.connect() as data:
        batch = manifest.latest_batch(meta, "yellow", month)
        if batch is None:
            raise NothingToLoad(f"no landed file for {month:%Y-%m}: run the landing step first")
        batch_id = batch["batch_id"]
        if batch["status"] == "loaded":
            log.info("batch %s is already in bronze: nothing to load", batch_id)
            return False

        key = batch["object_key"]
        file_name = key.rsplit("/", 1)[-1]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / file_name
                landing.download_file(key, local)
                digest = hashlib.sha256()
                with local.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != batch["sha256"]:
                    raise source.FileValidationError(
                        f"landed object {key} does not match the manifest checksum"
                    )

                # Replace the bronze partition and mark the batch loaded, atomically.
                with data.transaction():
                    rows = bronze.replace_month(
                        data,
                        local,
                        month,
                        batch_id,
                        file_name,
                        batch["schema_hash"],
                        settings.batch_rows,
                    )
                    manifest.update(data, batch_id, status="loaded", row_count_bronze=rows)
            log.info("bronze partition %s replaced: %s rows", bronze.partition_name(month), rows)
            return True
        except Exception as exc:
            # The batch stays 'landed': the file is valid and a retry of this step must
            # pick it up again. The bronze transaction was rolled back, so bronze still
            # holds the previous batch of the month.
            log.error("loading batch %s failed: %s", batch_id, exc)
            manifest.update(
                meta, batch_id, error_message=f"load failed: {type(exc).__name__}: {exc}"
            )
            raise
        finally:
            _write_manifest_object(meta, landing, batch_id, month)


def ingest_zones(settings: Settings, force: bool = False) -> str:
    """Ingest the taxi zone lookup. Full replace, skipped when the content is unchanged."""
    batch_id = uuid4()
    url = settings.zones_url
    landing = LandingZone(settings)

    with psycopg.connect(autocommit=True) as meta, psycopg.connect() as data:
        manifest.start(meta, batch_id, "taxi_zone", None, url, force)
        log.info("batch %s started: taxi zone lookup", batch_id)
        try:
            landing.ensure_bucket()
            response = httpx.get(url, follow_redirects=True, timeout=source.TIMEOUT)
            if response.status_code in (403, 404):
                raise source.SourceNotAvailable(
                    f"source file not available (HTTP {response.status_code}): {url}"
                )
            response.raise_for_status()
            content = response.content
            digest = hashlib.sha256(content).hexdigest()

            rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
            if not rows or rows[0] != ZONE_COLUMNS:
                raise ContractViolation(
                    f"zone lookup header is {rows[0] if rows else None}, expected {ZONE_COLUMNS}"
                )
            records = rows[1:]
            header_hash = hashlib.sha256(",".join(rows[0]).encode()).hexdigest()
            manifest.update(
                meta,
                batch_id,
                object_key=ZONES_OBJECT_KEY,
                file_size_bytes=len(content),
                sha256=digest,
                schema_hash=header_hash,
                schema_version="v1",
                row_count_file=len(records),
            )

            previous = manifest.last_loaded(meta, "taxi_zone", None)
            if previous and not force and previous["sha256"] == digest:
                log.info("zone lookup unchanged (same SHA-256): nothing to do")
                manifest.update(
                    meta,
                    batch_id,
                    status="skipped_unchanged",
                    row_count_bronze=previous["row_count_bronze"],
                )
                return "skipped_unchanged"

            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / "taxi_zone_lookup.csv"
                local.write_bytes(content)
                landing.upload_file(local, ZONES_OBJECT_KEY, digest)
            manifest.update(meta, batch_id, status="landed")

            ingested_at = datetime.now(UTC)
            with data.transaction(), data.cursor() as cur:
                cur.execute("TRUNCATE bronze.taxi_zone_raw")
                with cur.copy(
                    "COPY bronze.taxi_zone_raw "
                    "(locationid, borough, zone, service_zone, batch_id, source_file, ingested_at) "
                    "FROM STDIN"
                ) as copy:
                    for record in records:
                        copy.write_row([*record, batch_id, "taxi_zone_lookup.csv", ingested_at])
                manifest.update(data, batch_id, status="loaded", row_count_bronze=len(records))
            log.info("bronze.taxi_zone_raw replaced: %s rows", len(records))
            return "loaded"
        except Exception as exc:
            log.error("batch %s failed: %s", batch_id, exc)
            manifest.update(
                meta, batch_id, status="failed", error_message=f"{type(exc).__name__}: {exc}"
            )
            raise
        finally:
            _write_manifest_object(meta, landing, batch_id, None)
