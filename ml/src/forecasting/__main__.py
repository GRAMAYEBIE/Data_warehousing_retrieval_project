"""Train, evaluate and publish the demand forecast.

    python -m forecasting                  # trips and revenue: MLflow + ml schema
    python -m forecasting --target trips   # one target only
    python -m forecasting --dry-run        # backtest scores only: nothing written anywhere
    python -m forecasting --replay 2025-03 2025-04 2025-05
                                           # forecast recorded months as at the time, check them

Every live run first checks the published forecasts whose month is now recorded (check.py).

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
    b = result.backtests
    b = b[(b.segment == "all") | ((b.segment_type == "tier") & (b.segment == "high"))]
    table = b.pivot_table(index="month", columns=["method", "segment_type"], values="wmape")
    e = result.evaluation
    shown = e[e.segment_type.isin(["overall", "tier", "borough_day"])]
    cols = ["segment_type", "segment", "rows", "wmape", "baseline_wmape", "bias", "coverage_80"]
    with pd.option_context("display.width", 160, "display.float_format", "{:.3f}".format):
        return (
            f"backtests (WMAPE):\n{table.to_string()}\n"
            f"champion on {result.validated_month}:\n{shown[cols].to_string(index=False)}"
        )


def check_published(conn, history, target: str, uri: str | None, dry_run: bool) -> None:
    """Forecast against actual for every published forecast whose month is now recorded."""
    from forecasting import check

    for run in check.pending(conn, target, history.months):
        detail, daily = check.published_forecast(conn, run["run_id"], target)
        if detail.empty:
            print(f"check {run['forecast_month']}: forecast rows no longer kept", flush=True)
            continue
        result = check.compare(history, detail, daily, run["expected_wmape"])
        print(describe(result), flush=True)
        if dry_run:
            continue
        check.save(conn, run["run_id"], target, result, history.data_run, False, run["champion"])
        if uri:
            check.track(run["run_id"], result, uri)


def replay(conn, history, target: str, month: str, uri: str | None, dry_run: bool) -> None:
    """Forecast `month` from the months before it only, as at the time, then check it."""
    from forecasting import check, store, tracking

    before = (pd.Timestamp(f"{month}-01") - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    past = check.history_until(history, before)
    result = pipeline.run(past)
    if result.forecast_month != month:
        raise ValueError(f"replay of {month} forecast {result.forecast_month}")
    b = result.backtests
    expected = b[(b.method == result.champion) & (b.segment_type == "borough_day")
                 & (b.segment == "all")]["wmape"].mean()  # fmt: skip
    outcome = check.compare(history, result.forecast, result.daily, float(expected))
    print(f"replay {month} ({result.champion}, from {past.months[0]}..{before}): "
          + describe(outcome), flush=True)  # fmt: skip
    if dry_run:
        return
    run_id = (
        tracking.log(result, past.data_run, past.months, uri, replay=True)
        if uri
        else f"untracked-{uuid.uuid4().hex[:12]}"
    )
    store.save(conn, run_id, result, past.data_run, past.months, replay=True)
    check.save(conn, run_id, target, outcome, history.data_run, True, result.champion)
    if uri:
        check.track(run_id, outcome, uri)


def describe(result) -> str:
    expected = (
        f", expected {result.expected_wmape:.1%}" if result.expected_wmape is not None else ""
    )
    return (
        f"check {result.month}: error per borough and day {result.actual_wmape:.1%}{expected}"
        f" -> {result.status}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forecasting", description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="score only, write nothing")
    parser.add_argument(
        "--target", choices=[*data.TARGETS, "all"], default="all", help="what to forecast"
    )
    parser.add_argument(
        "--replay",
        nargs="+",
        metavar="YYYY-MM",
        help="forecast these recorded months as at the time and check them (no live run)",
    )
    args = parser.parse_args(argv)
    targets = list(data.TARGETS) if args.target == "all" else [args.target]
    uri = os.environ.get("MLFLOW_TRACKING_URI")

    with connect() as conn:
        for target in targets:
            start = time.monotonic()
            history = data.load(conn, target)
            print(
                f"\n== {target}: {len(history.zone_sk)} zones, {history.months[0]}.."
                f"{history.months[-1]} ({len(history.months)} months), "
                f"publication {history.data_run}",
                flush=True,
            )
            if args.replay:
                for month in args.replay:
                    replay(conn, history, target, month, uri, args.dry_run)
                continue
            # 1. The forecast of a month now recorded is checked before it is replaced.
            check_published(conn, history, target, uri, args.dry_run)
            # 2. The next month.
            result = pipeline.run(history)
            print(
                f"{result.decision}\nchampion: {result.champion}, scored on "
                f"{result.validated_month}; forecast for {result.forecast_month}\n"
                f"{summary(result)}",
                flush=True,
            )
            if args.dry_run:
                print("dry run: nothing written", flush=True)
                continue
            from forecasting import store, tracking

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
