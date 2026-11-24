"""Train, evaluate and publish the demand forecast.

    python -m forecasting            # full run: MLflow + ml schema (Airflow task, Compose job)
    python -m forecasting --dry-run  # validation scores only: nothing written anywhere

Connection: PGHOST, PGPORT, PGDATABASE, PGUSER (forecaster), FORECASTER_PASSWORD;
tracking: MLFLOW_TRACKING_URI.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import pandas as pd
import psycopg

from forecasting import data, pipeline


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("PGHOST", "postgres"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ["PGDATABASE"],
        user=os.environ.get("PGUSER", "forecaster"),
        password=os.environ["FORECASTER_PASSWORD"],
        application_name="demand_forecast",
    )


def summary(result: pipeline.Result) -> str:
    e = result.evaluation
    shown = e[e.segment_type.isin(["overall", "tier", "borough_day"])]
    cols = ["segment_type", "segment", "rows", "wmape", "baseline_wmape", "bias", "coverage_80"]
    with pd.option_context("display.width", 140, "display.float_format", "{:.3f}".format):
        return shown[cols].to_string(index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forecasting", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="score only, write nothing")
    args = parser.parse_args(argv)

    start = time.monotonic()
    with connect() as conn:
        history = data.load(conn)
        print(
            f"history: {len(history.zone_sk)} zones, {history.months[0]}..{history.months[-1]}"
            f" ({len(history.months)} months), publication {history.data_run}",
            flush=True,
        )
        result = pipeline.run(history)
        print(
            f"validated on {result.validated_month} ({result.rounds} trees), "
            f"forecast for {result.forecast_month}\n{summary(result)}",
            flush=True,
        )
        if args.dry_run:
            print("dry run: nothing written", flush=True)
            return 0
        from forecasting import store, tracking

        uri = os.environ.get("MLFLOW_TRACKING_URI")
        if uri:
            run_id = tracking.log(result, history.data_run, history.months, uri)
        else:  # tracking is part of the design: say so loudly, never silently skip it
            print("MLFLOW_TRACKING_URI is not set: the run is NOT tracked", file=sys.stderr)
            run_id = f"untracked-{uuid.uuid4().hex[:12]}"
        published = store.save(conn, run_id, result, history.data_run, history.months)
    verdict = "published" if published else "not published: " + "; ".join(result.reasons)
    print(f"run {run_id}: {verdict} ({time.monotonic() - start:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
