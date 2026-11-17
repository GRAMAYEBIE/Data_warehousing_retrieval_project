"""Command line entry point.

    python -m ingestion.cli check  --month 2025-01            # is the file published?
    python -m ingestion.cli land   --month 2025-01 [--force]  # source -> landing zone
    python -m ingestion.cli load   --month 2025-01            # landing zone -> bronze
    python -m ingestion.cli yellow --month 2025-01 [--force]  # land + load
    python -m ingestion.cli zones  [--force]                  # taxi zone lookup

Exit codes: 0 success (including "unchanged, nothing to do"), 2 source not available,
3 file or contract rejected, 4 nothing landed to load, 1 any other failure.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from ingestion.config import Settings
from ingestion.pipeline import (
    ContractViolation,
    NothingToLoad,
    check_yellow,
    ingest_yellow,
    ingest_zones,
    land_yellow,
    load_yellow,
)
from ingestion.source import FileValidationError, SourceNotAvailable

log = logging.getLogger(__name__)


def parse_month(value: str) -> date:
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"month must be YYYY-MM, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    for name, text in [
        ("check", "check that the monthly file is published"),
        ("load", "load the latest landed file of the month into bronze"),
    ]:
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--month", required=True, type=parse_month, help="YYYY-MM")

    for name, text in [
        ("land", "fetch, validate and store the monthly file in the landing zone"),
        ("yellow", "land then load one monthly file"),
    ]:
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--month", required=True, type=parse_month, help="YYYY-MM")
        sub.add_argument("--force", action="store_true", help="reload even if unchanged")

    zones = commands.add_parser("zones", help="ingest the taxi zone lookup")
    zones.add_argument("--force", action="store_true", help="reload even if unchanged")
    return parser


def run(args: argparse.Namespace, settings: Settings) -> str:
    if args.command == "check":
        check_yellow(settings, args.month)
        return "available"
    if args.command == "land":
        return land_yellow(settings, args.month, args.force)
    if args.command == "load":
        return "loaded" if load_yellow(settings, args.month) else "already_loaded"
    if args.command == "yellow":
        return ingest_yellow(settings, args.month, args.force)
    return ingest_zones(settings, args.force)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s"
    )
    # Request-level logs of the HTTP and S3 clients add noise without information.
    for noisy in ("httpx", "botocore", "boto3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        status = run(args, Settings.from_env())
    except SourceNotAvailable as exc:
        log.error("%s", exc)
        return 2
    except (FileValidationError, ContractViolation) as exc:
        log.error("rejected: %s", exc)
        return 3
    except NothingToLoad as exc:
        log.error("%s", exc)
        return 4
    except Exception:
        log.exception("unexpected failure")
        return 1

    log.info("final status: %s", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
