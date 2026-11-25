"""The ml schema: every run and its evaluation are kept; only the published forecast is.

Tables (owned by forecaster, readable by the dashboards and the assistant):
- ml.forecast_run: one row per run, with its data, months, champion, decision and scores;
- ml.forecast_evaluation: the champion's scores on the last month per segment;
- ml.forecast_backtest: both methods' scores per backtest month and segment;
- ml.demand_forecast: zone x day x hour of the published run;
- ml.demand_forecast_daily: borough x day of the published run, with its interval;
- views ml.current_forecast and ml.current_forecast_daily: the latest published run only;
- the same for revenue (USD): ml.revenue_forecast, ml.revenue_forecast_daily and their
  current_ views. A run's target is in forecast_run.target; for revenue, the column
  actual_trips of the scores holds USD.
A run that is not publishable keeps the previous forecast in place.
"""

from __future__ import annotations

import pandas as pd

from forecasting.pipeline import Result

DDL = """
CREATE TABLE IF NOT EXISTS ml.forecast_run (
    run_id          text PRIMARY KEY,           -- MLflow run id
    created_at      timestamptz NOT NULL DEFAULT now(),
    data_run        text NOT NULL,              -- publication of the training data
    history_months  text[] NOT NULL,
    validated_month text NOT NULL,
    forecast_month  text NOT NULL,
    model           text NOT NULL,
    rounds          integer NOT NULL,
    wmape           numeric,
    baseline_wmape  numeric,
    beats_baseline  boolean NOT NULL,
    published       boolean NOT NULL DEFAULT false,
    reasons         text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS ml.forecast_evaluation (
    run_id         text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    segment_type   text NOT NULL,               -- overall, borough, tier, borough_day
    segment        text NOT NULL,
    rows           integer NOT NULL,
    actual_trips   numeric NOT NULL,
    mae            numeric,
    wmape          numeric,
    bias           numeric,
    baseline_mae   numeric,
    baseline_wmape numeric,
    coverage_80    numeric,
    PRIMARY KEY (run_id, segment_type, segment)
);
CREATE TABLE IF NOT EXISTS ml.demand_forecast (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    zone_sk         integer NOT NULL,
    zone_name       text NOT NULL,
    borough         text NOT NULL,
    date_day        date NOT NULL,
    pickup_hour     smallint NOT NULL,
    predicted_trips real NOT NULL,
    lower_80        real NOT NULL,
    upper_80        real NOT NULL,
    demand_tier     text NOT NULL,
    low_confidence  boolean NOT NULL,
    PRIMARY KEY (run_id, zone_sk, date_day, pickup_hour)
);
CREATE TABLE IF NOT EXISTS ml.demand_forecast_daily (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    borough         text NOT NULL,
    date_day        date NOT NULL,
    predicted_trips real NOT NULL,
    lower_80        real NOT NULL,
    upper_80        real NOT NULL,
    PRIMARY KEY (run_id, borough, date_day)
);
-- Champion and challenger (added after the first runs, which were model-only).
ALTER TABLE ml.forecast_run ADD COLUMN IF NOT EXISTS champion text NOT NULL DEFAULT 'model';
ALTER TABLE ml.forecast_run ADD COLUMN IF NOT EXISTS decision text;
ALTER TABLE ml.demand_forecast ADD COLUMN IF NOT EXISTS method text NOT NULL DEFAULT 'model';
CREATE TABLE IF NOT EXISTS ml.forecast_backtest (
    run_id         text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    month          text NOT NULL,               -- month forecast from the weeks before it
    method         text NOT NULL,               -- model or baseline
    segment_type   text NOT NULL,
    segment        text NOT NULL,
    rows           integer NOT NULL,
    actual_trips   numeric NOT NULL,
    mae            numeric,
    wmape          numeric,
    bias           numeric,
    coverage_80    numeric,
    PRIMARY KEY (run_id, month, method, segment_type, segment)
);
-- Revenue forecast (USD, total amount of valid trips): same run structure, own tables.
ALTER TABLE ml.forecast_run ADD COLUMN IF NOT EXISTS target text NOT NULL DEFAULT 'trips';
-- A forecast replayed as if made at the time, for the forecast-against-actual history.
ALTER TABLE ml.forecast_run ADD COLUMN IF NOT EXISTS replay boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS ml.revenue_forecast (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    zone_sk         integer NOT NULL,
    zone_name       text NOT NULL,
    borough         text NOT NULL,
    date_day        date NOT NULL,
    pickup_hour     smallint NOT NULL,
    predicted_usd   real NOT NULL,
    lower_80        real NOT NULL,
    upper_80        real NOT NULL,
    demand_tier     text NOT NULL,
    low_confidence  boolean NOT NULL,
    method          text NOT NULL,
    PRIMARY KEY (run_id, zone_sk, date_day, pickup_hour)
);
CREATE TABLE IF NOT EXISTS ml.revenue_forecast_daily (
    run_id          text NOT NULL REFERENCES ml.forecast_run ON DELETE CASCADE,
    borough         text NOT NULL,
    date_day        date NOT NULL,
    predicted_usd   real NOT NULL,
    lower_80        real NOT NULL,
    upper_80        real NOT NULL,
    PRIMARY KEY (run_id, borough, date_day)
);
CREATE OR REPLACE VIEW ml.current_run AS
    SELECT * FROM ml.forecast_run WHERE published AND target = 'trips'
    ORDER BY created_at DESC LIMIT 1;
CREATE OR REPLACE VIEW ml.current_revenue_run AS
    SELECT * FROM ml.forecast_run WHERE published AND target = 'revenue'
    ORDER BY created_at DESC LIMIT 1;
CREATE OR REPLACE VIEW ml.current_forecast AS
    SELECT f.* FROM ml.demand_forecast AS f JOIN ml.current_run USING (run_id);
CREATE OR REPLACE VIEW ml.current_forecast_daily AS
    SELECT f.* FROM ml.demand_forecast_daily AS f JOIN ml.current_run USING (run_id);
CREATE OR REPLACE VIEW ml.current_revenue_forecast AS
    SELECT f.* FROM ml.revenue_forecast AS f JOIN ml.current_revenue_run USING (run_id);
CREATE OR REPLACE VIEW ml.current_revenue_forecast_daily AS
    SELECT f.* FROM ml.revenue_forecast_daily AS f JOIN ml.current_revenue_run USING (run_id);
"""

# Where each target's published forecast goes: zone x day x hour table, its value column,
# and the borough x day table.
OUTPUT = {
    "trips": ("ml.demand_forecast", "predicted_trips", "ml.demand_forecast_daily"),
    "revenue": ("ml.revenue_forecast", "predicted_usd", "ml.revenue_forecast_daily"),
}

EVALUATION_COLUMNS = [
    "segment_type", "segment", "rows", "actual_trips", "mae", "wmape", "bias",
    "baseline_mae", "baseline_wmape", "coverage_80",
]  # fmt: skip


def _none(value):
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def save(
    conn,
    run_id: str,
    result: Result,
    data_run: str,
    history_months: list[str],
    replay: bool = False,
) -> bool:
    """Write the run in one transaction; returns True when its forecast was published. A
    replay is recorded (run, scores, backtests) but never published."""
    overall = result.evaluation[result.evaluation.segment_type == "overall"].iloc[0]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(
            """INSERT INTO ml.forecast_run (run_id, data_run, history_months, validated_month,
                   forecast_month, model, rounds, wmape, baseline_wmape, beats_baseline, reasons,
                   champion, decision, target, replay)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                run_id, data_run, history_months, result.validated_month, result.forecast_month,
                "challenger: lightgbm poisson + quantile 10/90; baseline: seasonal naive 4 weeks",
                result.rounds, float(overall.wmape), float(overall.baseline_wmape),
                result.beats_baseline, result.reasons, result.champion, result.decision,
                result.target, replay,
            ),
        )  # fmt: skip
        cur.executemany(
            f"INSERT INTO ml.forecast_evaluation (run_id, {', '.join(EVALUATION_COLUMNS)}) "
            f"VALUES (%s, {', '.join(['%s'] * len(EVALUATION_COLUMNS))})",
            [
                (run_id, *[_none(row.get(c)) for c in EVALUATION_COLUMNS])
                for row in result.evaluation.to_dict("records")
            ],
        )
        backtest_columns = ["rows", "actual_trips", "mae", "wmape", "bias", "coverage_80"]
        cur.executemany(
            "INSERT INTO ml.forecast_backtest (run_id, month, method, segment_type, segment, "
            f"{', '.join(backtest_columns)}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (run_id, row["month"], row["method"], row["segment_type"], row["segment"],
                 *[_none(row.get(c)) for c in backtest_columns])
                for row in result.backtests.to_dict("records")
            ],
        )  # fmt: skip
        if replay or not result.publishable:
            return False
        # Only the published forecast is kept in full; earlier runs stay in forecast_run,
        # forecast_evaluation, forecast_backtest and MLflow. (Table names are constants.)
        table, value, daily_table = OUTPUT[result.target]
        cur.execute(f"DELETE FROM {table} WHERE run_id <> %s", (run_id,))
        cur.execute(f"DELETE FROM {daily_table} WHERE run_id <> %s", (run_id,))
        with cur.copy(
            f"COPY {table} (run_id, zone_sk, zone_name, borough, date_day, pickup_hour,"
            f" {value}, lower_80, upper_80, demand_tier, low_confidence, method) FROM STDIN"
        ) as copy:
            for r in result.forecast.itertuples(index=False):
                copy.write_row(
                    (
                        run_id,
                        int(r.zone_sk),
                        r.zone_name,
                        r.borough,
                        r.date_day,
                        int(r.pickup_hour),
                        float(r.predicted),
                        float(r.lower),
                        float(r.upper),
                        r.tier,
                        bool(r.low_confidence),
                        r.method,
                    )
                )
        cur.executemany(
            f"INSERT INTO {daily_table} VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (run_id, r.borough, r.date_day, float(r.predicted), float(r.lower), float(r.upper))
                for r in result.daily.itertuples()
            ],
        )
        cur.execute("UPDATE ml.forecast_run SET published = true WHERE run_id = %s", (run_id,))
    return True
