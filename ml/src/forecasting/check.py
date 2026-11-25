"""Forecast against actual: every forecast month is checked once its trips are published.

The loop the platform runs, month after month (the monthly batch or the Kafka stream
publishes a month; the forecasting job starts on that publication):

1. check: each published forecast whose month is now in the published data is compared
   with what was recorded, before anything else (the next run replaces the forecast);
2. train, choose and publish the forecast of the following month (pipeline.run).

The check scores the forecast as it was published, with the measures of the backtests
(evaluate.report: WMAPE, bias and 80 % coverage per zone-hour, borough, demand tier and
borough-day), plus the coverage of the borough-day range a planner reads. It compares
the error with what the backtests promised: an error per borough and day more than 1.5
times the expected one (and 3 points above it) marks the month as drift, a signal that
the method no longer holds (a new pattern, an event, a data problem).

The scores stay in ml.forecast_check and the borough-day comparison in
ml.forecast_check_daily, so the history survives after the forecast itself is replaced;
they are also logged on the MLflow run that made the forecast.

Replay: a month can be forecast as if it were made at the time, from the months before
it only (`history_until`), and checked at once. This gives the check a history before
the first live month arrives; replays are flagged as such everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from forecasting import evaluate
from forecasting.data import History

DRIFT_RATIO = 1.5  # actual error / expected error
DRIFT_MARGIN = 0.03  # and at least 3 points above it

CHECK_DDL = """
CREATE TABLE IF NOT EXISTS ml.forecast_check (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    target          text NOT NULL,              -- trips or revenue
    month           text NOT NULL,              -- the forecast month, now recorded
    segment_type    text NOT NULL,              -- overall, borough, tier, borough_day
    segment         text NOT NULL,
    rows            integer NOT NULL,
    actual          numeric NOT NULL,           -- recorded total (trips or USD)
    predicted       numeric NOT NULL,           -- forecast total
    wmape           numeric,
    bias            numeric,
    coverage_80     numeric,                    -- zone-hour, or borough-day for borough_day
    PRIMARY KEY (run_id, segment_type, segment)
);
CREATE TABLE IF NOT EXISTS ml.forecast_check_run (
    run_id          text PRIMARY KEY REFERENCES ml.forecast_run ON DELETE CASCADE,
    target          text NOT NULL,
    month           text NOT NULL,
    checked_at      timestamptz NOT NULL DEFAULT now(),
    data_run        text NOT NULL,              -- publication that brought the actuals
    replay          boolean NOT NULL,           -- forecast replayed, not made live
    method          text NOT NULL,              -- champion that made the forecast
    expected_wmape  numeric,                    -- borough-day error promised by the backtests
    actual_wmape    numeric,                    -- borough-day error observed
    status          text NOT NULL               -- ok or drift
);
CREATE TABLE IF NOT EXISTS ml.forecast_check_daily (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    borough         text NOT NULL,
    date_day        date NOT NULL,
    predicted       real NOT NULL,
    lower_80        real NOT NULL,
    upper_80        real NOT NULL,
    actual          real NOT NULL,
    PRIMARY KEY (run_id, borough, date_day)
);
ALTER TABLE ml.forecast_run ADD COLUMN IF NOT EXISTS replay boolean NOT NULL DEFAULT false;
CREATE OR REPLACE VIEW ml.forecast_checks AS
    SELECT c.*, r.created_at, r.data_run AS forecast_data_run
    FROM ml.forecast_check_run AS c JOIN ml.forecast_run AS r USING (run_id);
"""


@dataclass
class Check:
    month: str
    scores: pd.DataFrame  # segment_type, segment, rows, actual, predicted, wmape, bias, coverage
    daily: pd.DataFrame  # borough, date_day, predicted, lower, upper, actual
    expected_wmape: float | None
    actual_wmape: float
    status: str  # ok | drift


def history_until(history: History, month: str) -> History:
    """The history as it was at the end of `month` (a replay sees nothing later)."""
    end = pd.Timestamp(f"{month}-01") + pd.offsets.MonthEnd(0)
    keep = int((history.days <= end).sum())
    return History(
        zone_sk=history.zone_sk,
        zone_name=history.zone_name,
        borough=history.borough,
        days=history.days[:keep],
        trips=history.trips[:, :keep, :],
        holidays=history.holidays,
        data_run=f"{history.data_run} (until {month})",
        target=history.target,
        scale=history.scale,
    )


def recorded(history: History, forecast: pd.DataFrame) -> np.ndarray:
    """The recorded value of each forecast row (zone_sk, date_day, pickup_hour); a zone the
    history does not know recorded nothing."""
    zone = pd.Index(history.zone_sk).get_indexer(forecast["zone_sk"].to_numpy())
    day = history.days.get_indexer(pd.to_datetime(forecast["date_day"]))
    if (day < 0).any():
        raise ValueError("the forecast month is not fully recorded yet")
    values = history.trips[np.clip(zone, 0, None), day, forecast["pickup_hour"].to_numpy(int)]
    return np.where(zone >= 0, values, 0.0)


def status_of(actual_wmape: float, expected_wmape: float | None) -> str:
    if expected_wmape is None or not np.isfinite(expected_wmape):
        return "ok"
    drift = actual_wmape > DRIFT_RATIO * expected_wmape and (
        actual_wmape > expected_wmape + DRIFT_MARGIN
    )
    return "drift" if drift else "ok"


def compare(
    history: History, forecast: pd.DataFrame, daily: pd.DataFrame, expected_wmape: float | None
) -> Check:
    """forecast: zone x day x hour rows (zone_sk, borough, tier, date_day, pickup_hour,
    predicted, lower, upper); daily: borough x day (predicted, lower, upper)."""
    frame = forecast.copy()
    frame["actual"] = recorded(history, frame)
    frame["baseline"] = frame["predicted"]  # report() needs it; not shown for a check
    report = evaluate.report(frame)
    totals = {
        ("overall", "all"): frame,
        **{("borough", b): p for b, p in frame.groupby("borough")},
        **{("tier", t): p for t, p in frame.groupby("tier")},
        ("borough_day", "all"): frame,
        **{("borough_day", b): p for b, p in frame.groupby("borough")},
    }
    report["predicted"] = [
        float(totals[(t, s)]["predicted"].sum()) for t, s in zip(
            report["segment_type"], report["segment"], strict=True)
    ]  # fmt: skip

    actual_daily = frame.groupby(["borough", "date_day"], as_index=False)["actual"].sum()
    days = daily.merge(actual_daily, on=["borough", "date_day"], how="left").fillna({"actual": 0})
    inside = (days["actual"] >= days["lower"]) & (days["actual"] <= days["upper"])
    # Borough-day: the coverage of the borough-day range, the one shown to planners.
    day_rows = report["segment_type"] == "borough_day"
    report.loc[day_rows, "coverage_80"] = [
        float(inside[days["borough"] == s].mean()) if s != "all" else float(inside.mean())
        for s in report.loc[day_rows, "segment"]
    ]
    scores = report.rename(columns={"actual_trips": "actual"})[
        ["segment_type", "segment", "rows", "actual", "predicted", "wmape", "bias", "coverage_80"]
    ]
    observed = float(
        scores.loc[
            (scores.segment_type == "borough_day") & (scores.segment == "all"), "wmape"
        ].iloc[0]
    )
    month = pd.Timestamp(frame["date_day"].min()).strftime("%Y-%m")
    return Check(month, scores, days, expected_wmape, observed, status_of(observed, expected_wmape))


# ------------------------------------------------------------------ database
PENDING_SQL = """
SELECT r.run_id, r.forecast_month, r.champion,
       (SELECT avg(b.wmape)::float FROM ml.forecast_backtest AS b
        WHERE b.run_id = r.run_id AND b.method = r.champion
          AND b.segment_type = 'borough_day' AND b.segment = 'all') AS expected_wmape
FROM ml.forecast_run AS r
WHERE r.published AND r.target = %(target)s AND r.forecast_month = ANY(%(months)s)
  AND NOT EXISTS (SELECT 1 FROM ml.forecast_check_run AS c WHERE c.run_id = r.run_id)
ORDER BY r.created_at
"""


def pending(conn, target: str, months: list[str]) -> list[dict]:
    """Published forecasts whose month is now recorded and not checked yet."""
    with conn.cursor() as cur:
        cur.execute(CHECK_DDL)
        cur.execute(PENDING_SQL, {"target": target, "months": months})
        columns = [c.name for c in cur.description]
        out = [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]
    conn.commit()
    return out


def published_forecast(conn, run_id: str, target: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The zone-hour and borough-day forecast of a published run, from the ml schema."""
    from forecasting.store import OUTPUT

    table, value, daily_table = OUTPUT[target]  # constants, not input
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT zone_sk, borough, demand_tier AS tier, date_day, pickup_hour, "
            f"{value}::float8 AS predicted, lower_80::float8 AS lower, "
            f"upper_80::float8 AS upper FROM {table} WHERE run_id = %s",
            (run_id,),
        )
        detail = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
        cur.execute(
            f"SELECT borough, date_day, {value}::float8 AS predicted, lower_80::float8 AS lower, "
            f"upper_80::float8 AS upper FROM {daily_table} WHERE run_id = %s",
            (run_id,),
        )
        daily = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    return detail, daily


def save(conn, run_id: str, target: str, check: Check, data_run: str, replay: bool,
         method: str) -> None:  # fmt: skip
    """One transaction: the scores, the borough-day comparison and the verdict."""

    def value(v):
        return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else v

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(CHECK_DDL)
        cur.executemany(
            "INSERT INTO ml.forecast_check (run_id, target, month, segment_type, segment, rows, "
            "actual, predicted, wmape, bias, coverage_80) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (run_id, target, check.month, r["segment_type"], r["segment"], int(r["rows"]),
                 float(r["actual"]), float(r["predicted"]), value(r["wmape"]), value(r["bias"]),
                 value(r["coverage_80"]))
                for r in check.scores.to_dict("records")
            ],
        )  # fmt: skip
        cur.executemany(
            "INSERT INTO ml.forecast_check_daily VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (run_id, r.borough, r.date_day, float(r.predicted), float(r.lower),
                 float(r.upper), float(r.actual))
                for r in check.daily.itertuples()
            ],
        )  # fmt: skip
        cur.execute(
            "INSERT INTO ml.forecast_check_run (run_id, target, month, data_run, replay, method, "
            "expected_wmape, actual_wmape, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, target, check.month, data_run, replay, method, value(check.expected_wmape),
             check.actual_wmape, check.status),
        )  # fmt: skip


def track(run_id: str, check: Check, tracking_uri: str) -> None:
    """The check on the MLflow run that made the forecast (best effort)."""
    import mlflow
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()
    for r in check.scores.to_dict("records"):
        if r["segment"] == "all" and r["wmape"] == r["wmape"]:
            key = f"actual.{r['segment_type']}.wmape"
            client.log_metric(run_id, key, float(r["wmape"]))
    client.set_tag(run_id, "checked_month", check.month)
    client.set_tag(run_id, "check_status", check.status)
