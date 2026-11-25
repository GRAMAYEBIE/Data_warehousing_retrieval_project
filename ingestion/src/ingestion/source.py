"""Access to the TLC source: availability check, download, file validation."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pyarrow.parquet as pq

log = logging.getLogger(__name__)
PARQUET_MAGIC = b"PAR1"
TIMEOUT = httpx.Timeout(30.0, read=300.0)


class SourceNotAvailable(Exception):
    """The source file does not exist (yet) at the expected URL."""


class FileValidationError(Exception):
    """The downloaded file is not what the contract expects (type, size, content)."""


@dataclass(frozen=True)
class SourceInfo:
    url: str
    etag: str | None
    size: int | None


@dataclass(frozen=True)
class Download:
    path: Path
    size: int
    sha256: str


def head(url: str, attempts: int | None = None, wait_s: float | None = None) -> SourceInfo:
    """Check that the source file exists. CloudFront answers 403 for a missing month.

    Two different failures, two different waits: a month not published yet
    (SourceNotAvailable) is retried by Airflow hours later; a network error or a server
    error is retried here after a few minutes (INGEST_NETWORK_RETRIES times, every
    INGEST_NETWORK_RETRY_S seconds), instead of waiting six hours for a passing glitch."""
    attempts = attempts or int(os.environ.get("INGEST_NETWORK_RETRIES", "6"))
    wait_s = float(os.environ.get("INGEST_NETWORK_RETRY_S", "300")) if wait_s is None else wait_s
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.head(url, follow_redirects=True, timeout=TIMEOUT)
            if response.status_code in (403, 404):
                raise SourceNotAvailable(
                    f"source file not available (HTTP {response.status_code}): {url}"
                )
            response.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            server_error = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code >= 500
            )
            if not server_error or attempt == attempts:
                raise
            log.warning(
                "source check failed (%s), attempt %d of %d: retrying in %.0f s",
                type(exc).__name__, attempt, attempts, wait_s,
            )  # fmt: skip
            time.sleep(wait_s)
    size = response.headers.get("content-length")
    etag = response.headers.get("etag")
    return SourceInfo(
        url=url, etag=etag.strip('"') if etag else None, size=int(size) if size else None
    )


def download(url: str, dest: Path) -> Download:
    """Stream the file to disk while computing its SHA-256."""
    digest = hashlib.sha256()
    size = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=TIMEOUT) as response:
        if response.status_code in (403, 404):
            raise SourceNotAvailable(
                f"source file not available (HTTP {response.status_code}): {url}"
            )
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    return Download(path=dest, size=size, sha256=digest.hexdigest())


def validate_parquet(path: Path, expected_size: int | None) -> pq.ParquetFile:
    """File-type, size and readability checks before anything is stored."""
    size = path.stat().st_size
    if expected_size is not None and size != expected_size:
        raise FileValidationError(
            f"size mismatch: downloaded {size} bytes, expected {expected_size}"
        )
    if size < 12:
        raise FileValidationError(f"file too small to be Parquet ({size} bytes)")
    with path.open("rb") as handle:
        start = handle.read(4)
        handle.seek(-4, 2)
        end = handle.read(4)
    if start != PARQUET_MAGIC or end != PARQUET_MAGIC:
        raise FileValidationError("not a Parquet file (magic bytes PAR1 missing)")
    try:
        parquet_file = pq.ParquetFile(path)
    except Exception as exc:  # pyarrow raises several error types for corrupt files
        raise FileValidationError(f"unreadable Parquet metadata: {exc}") from exc
    if parquet_file.metadata.num_rows == 0:
        raise FileValidationError("Parquet file contains no rows")
    return parquet_file
