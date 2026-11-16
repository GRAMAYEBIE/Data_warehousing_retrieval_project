"""Runtime configuration, read from environment variables only (no secrets in code)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    tlc_base_url: str
    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    contracts_dir: Path
    batch_rows: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            tlc_base_url=os.environ.get(
                "TLC_BASE_URL", "https://d37ci6vzurychx.cloudfront.net"
            ).rstrip("/"),
            s3_endpoint_url=os.environ["S3_ENDPOINT_URL"],
            s3_access_key=os.environ["S3_ACCESS_KEY"],
            s3_secret_key=os.environ["S3_SECRET_KEY"],
            s3_bucket=os.environ["S3_BUCKET"],
            contracts_dir=Path(os.environ.get("CONTRACTS_DIR", "contracts")),
            batch_rows=int(os.environ.get("INGEST_BATCH_ROWS", "200000")),
        )

    def yellow_url(self, year: int, month: int) -> str:
        return f"{self.tlc_base_url}/trip-data/yellow_tripdata_{year:04d}-{month:02d}.parquet"

    @property
    def zones_url(self) -> str:
        return f"{self.tlc_base_url}/misc/taxi_zone_lookup.csv"


def yellow_object_key(year: int, month: int) -> str:
    """Partitioned landing path for a monthly file."""
    return (
        f"raw/yellow/year={year:04d}/month={month:02d}/"
        f"yellow_tripdata_{year:04d}-{month:02d}.parquet"
    )


def manifest_object_key(dataset: str, batch_id: str, year: int | None, month: int | None) -> str:
    if year is None or month is None:
        return f"manifests/{dataset}/{batch_id}.json"
    return f"manifests/{dataset}/year={year:04d}/month={month:02d}/{batch_id}.json"
