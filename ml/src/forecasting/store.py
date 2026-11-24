"""The ml schema: every run and its evaluation are kept; only the published forecast is.

Tables (owned by forecaster, readable by the dashboards and the assistant):
- ml.forecast_run: one row per run, with its data, months, decision and headline scores;
- ml.forecast_evaluation: the scores of each run per segment (evaluate.report);
- ml.demand_forecast: zone x day x hour of the published run;
- ml.demand_forecast_daily: borough x day of the published run, with its interval;
- views ml.current_forecast and ml.current_forecast_daily: the latest published run only.
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
CREATE OR REPLACE VIEW ml.current_run AS
    SELECT * FROM ml.forecast_run WHERE published ORDER BY created_at DESC LIMIT 1;
CREATE OR REPLACE VIEW ml.current_forecast AS
    SELECT f.* FROM ml.demand_forecast AS f JOIN ml.current_run USING (run_id);
CREATE OR REPLACE VIEW ml.current_forecast_daily AS
    SELECT f.* FROM ml.demand_forecast_daily AS f JOIN ml.current_run USING (run_id);
"""

EVALUATION_COLUMNS = [
    "segment_type", "segment", "rows", "actual_trips", "mae", "wmape", "bias",
    "baseline_mae", "baseline_wmape", "coverage_80",
]  # fmt: skip


def _none(value):
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def save(conn, run_id: str, result: Result, data_run: str, history_months: list[str]) -> bool:
    """Write the run in one transaction; returns True when its forecast was published."""
    overall = result.evaluation[result.evaluation.segment_type == "overall"].iloc[0]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(
            """INSERT INTO ml.forecast_run (run_id, data_run, history_months, validated_month,
                   forecast_month, model, rounds, wmape, baseline_wmape, beats_baseline, reasons)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                run_id, data_run, history_months, result.validated_month, result.forecast_month,
                "lightgbm poisson + quantile 10/90", result.rounds, float(overall.wmape),
                float(overall.baseline_wmape), result.beats_baseline, result.reasons,
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
        if not result.publishable:
            return False
        # Only the published forecast is kept in full; earlier runs stay in forecast_run,
        # forecast_evaluation and MLflow.
        cur.execute("DELETE FROM ml.demand_forecast WHERE run_id <> %s", (run_id,))
        cur.execute("DELETE FROM ml.demand_forecast_daily WHERE run_id <> %s", (run_id,))
        with cur.copy(
            "COPY ml.demand_forecast (run_id, zone_sk, zone_name, borough, date_day, pickup_hour,"
            " predicted_trips, lower_80, upper_80, demand_tier, low_confidence) FROM STDIN"
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
                    )
                )
        cur.executemany(
            "INSERT INTO ml.demand_forecast_daily VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (run_id, r.borough, r.date_day, float(r.predicted), float(r.lower), float(r.upper))
                for r in result.daily.itertuples()
            ],
        )
        cur.execute("UPDATE ml.forecast_run SET published = true WHERE run_id = %s", (run_id,))
    return True
