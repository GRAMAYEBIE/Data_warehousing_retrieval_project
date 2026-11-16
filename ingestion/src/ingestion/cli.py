"""Command line entry point.

    python -m ingestion.cli yellow --month 2025-01 [--force]
    python -m ingestion.cli zones [--force]

Exit codes: 0 loaded or skipped, 2 source not available, 3 file or contract rejected,
1 any other failure.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from ingestion.config import Settings
from ingestion.pipeline import ContractViolation, ingest_yellow, ingest_zones
from ingestion.source import FileValidationError, SourceNotAvailable


def parse_month(value: str) -> date:
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"month must be YYYY-MM, got {value!r}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    yellow = commands.add_parser("yellow", help="ingest one monthly Yellow Taxi file")
    yellow.add_argument("--month", required=True, type=parse_month, help="YYYY-MM")
    yellow.add_argument("--force", action="store_true", help="reload even if unchanged")

    zones = commands.add_parser("zones", help="ingest the taxi zone lookup")
    zones.add_argument("--force", action="store_true", help="reload even if unchanged")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    # Request-level logs of the HTTP and S3 clients add noise without information.
    for noisy in ("httpx", "botocore", "boto3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = Settings.from_env()
    try:
        if args.command == "yellow":
            status = ingest_yellow(settings, args.month, args.force)
        else:
            status = ingest_zones(settings, args.force)
    except SourceNotAvailable:
        return 2
    except (FileValidationError, ContractViolation):
        return 3
    except Exception:
        logging.getLogger(__name__).exception("unexpected failure")
        return 1

    logging.getLogger(__name__).info("final status: %s", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
