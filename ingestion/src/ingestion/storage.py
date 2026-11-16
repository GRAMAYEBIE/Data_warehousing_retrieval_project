"""S3-compatible landing zone (RustFS)."""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ingestion.config import Settings


class LandingZone:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def object_size(self, key: str) -> int | None:
        """Size of the object, or None when it does not exist."""
        try:
            return self._client.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def upload_file(self, path: Path, key: str, sha256: str) -> None:
        """Same key on every run: re-landing a month overwrites, never duplicates."""
        self._client.upload_file(
            str(path), self.bucket, key, ExtraArgs={"Metadata": {"sha256": sha256}}
        )

    def put_json(self, key: str, payload: dict) -> None:
        body = json.dumps(payload, default=str, indent=2, sort_keys=True).encode("utf-8")
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )
