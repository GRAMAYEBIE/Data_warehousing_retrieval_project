"""The Forecast page: the published demand forecast and how well its model did.

Fixed queries on the ml schema (written by the forecasting job, read here as ai_reader):
the latest published run and its champion (the seasonal baseline or the model), the
month-by-month backtests of both, the champion's evaluation on the last month, the
forecast per borough and day with its 80 % interval, the busiest zones and the hourly
profile; plus the actual trips of the validated month for comparison. A forecast is an
estimate: it is never mixed with the governed measures.
"""

from __future__ import annotations

import psycopg

RUN_SQL = """
SELECT run_id, data_run, created_at::text, history_months, validated_month, forecast_month,
       model, rounds, wmape::float, baseline_wmape::float, champion, decision
FROM ml.current_run
"""
EVALUATION_SQL = """
SELECT segment_type, segment, rows, actual_trips::float, mae::float, wmape::float, bias::float,
       baseline_mae::float, baseline_wmape::float, coverage_80::float
FROM ml.forecast_evaluation WHERE run_id = %(run)s
ORDER BY segment_type, actual_trips DESC
"""
TABLES = {
    # Champion and challenger month by month (rolling backtests of the run).
    "backtests": """
        SELECT month, method, segment_type, segment, rows, wmape::float AS wmape,
               bias::float AS bias
        FROM ml.forecast_backtest
        WHERE run_id = %(run)s AND segment_type IN ('overall', 'tier', 'borough_day')
        ORDER BY month, method, segment_type, segment
        LIMIT 200""",
    "daily": """
        SELECT borough, date_day::text, predicted_trips::float AS predicted,
               lower_80::float AS lower, upper_80::float AS upper
        FROM ml.demand_forecast_daily WHERE run_id = %(run)s
        ORDER BY borough, date_day
        LIMIT 2000""",
    # Monthly totals per zone, without an interval: the hourly 10th and 90th percentiles
    # cannot be added up into one (the sum would be far too wide).
    "zones": """
        SELECT zone_name, borough, sum(predicted_trips)::float AS predicted,
               min(demand_tier) AS demand_tier, bool_or(low_confidence) AS low_confidence
        FROM ml.demand_forecast WHERE run_id = %(run)s
        GROUP BY zone_name, borough
        ORDER BY predicted DESC
        LIMIT 10""",
    "hourly": """
        SELECT pickup_hour, (sum(predicted_trips) / count(DISTINCT date_day))::float AS predicted
        FROM ml.demand_forecast WHERE run_id = %(run)s
        GROUP BY pickup_hour ORDER BY pickup_hour
        LIMIT 24""",
    # Trips actually recorded in the validated month, per borough, for comparison.
    "last_actual": """
        SELECT pickup_borough AS borough, sum(trip_count)::float AS trips,
               count(DISTINCT date_day) AS days
        FROM analytics.mv_trips_daily
        WHERE quality_status = 'valid' AND month_start = %(month)s::date
        GROUP BY pickup_borough
        LIMIT 20""",
}


REVENUE_RUN_SQL = RUN_SQL.replace("ml.current_run", "ml.current_revenue_run")
REVENUE_TABLES = {
    "revenue_daily": """
        SELECT borough, date_day::text, predicted_usd::float AS predicted,
               lower_80::float AS lower, upper_80::float AS upper
        FROM ml.revenue_forecast_daily WHERE run_id = %(run)s
        ORDER BY borough, date_day
        LIMIT 2000""",
    "revenue_last_actual": """
        SELECT pickup_borough AS borough, sum(sum_total_amount)::float AS revenue,
               count(DISTINCT date_day) AS days
        FROM analytics.mv_trips_daily
        WHERE quality_status = 'valid' AND month_start = %(month)s::date
        GROUP BY pickup_borough
        LIMIT 20""",
}


# Forecast against actual (ml/check.py): each forecast month checked once recorded. One
# check per target and month: the live forecast when there is one, else the replay.
LATEST_CHECKS = """
WITH latest AS (
    SELECT DISTINCT ON (target, month) *
    FROM ml.forecast_check_run
    ORDER BY target, month, replay, checked_at DESC
)"""
CHECK_TABLES = {
    "checks": LATEST_CHECKS
    + """
        SELECT run_id, target, month, replay, method, expected_wmape::float AS expected_wmape,
               actual_wmape::float AS actual_wmape, status, checked_at::text AS checked_at
        FROM latest
        ORDER BY month, target
        LIMIT 48""",
    "check_scores": LATEST_CHECKS
    + """
        SELECT l.target, l.month, s.segment_type, s.segment, s.actual::float AS actual,
               s.predicted::float AS predicted, s.wmape::float AS wmape, s.bias::float AS bias,
               s.coverage_80::float AS coverage_80
        FROM latest AS l JOIN ml.forecast_check AS s USING (run_id)
        WHERE s.segment_type IN ('overall', 'borough_day')
        ORDER BY l.month, l.target, s.segment_type, s.segment
        LIMIT 600""",
    # Borough x day, forecast and recorded, of the last twelve months checked.
    "check_daily": LATEST_CHECKS
    + """
        SELECT l.target, l.month, d.borough, d.date_day::text AS date_day,
               d.predicted::float AS predicted, d.lower_80::float AS lower,
               d.upper_80::float AS upper, d.actual::float AS actual
        FROM latest AS l JOIN ml.forecast_check_daily AS d USING (run_id)
        WHERE l.month IN (SELECT DISTINCT month FROM latest ORDER BY month DESC LIMIT 12)
        ORDER BY l.target, l.month, d.borough, d.date_day
        LIMIT 5000""",
}


def compute(store) -> dict:
    """The page's data; {"available": False, ...} when no forecast was published yet."""
    try:
        columns, rows, _ = store.query(RUN_SQL, {})
    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        return {"available": False, "message": "No forecast yet: run the demand forecast job."}
    if not rows:
        return {"available": False, "message": "No published forecast yet."}
    run = dict(zip(columns, rows[0], strict=True))
    params = {"run": run["run_id"], "month": f"{run['validated_month']}-01"}
    ev_columns, ev_rows, _ = store.query(EVALUATION_SQL, params)
    tables = {}

    def add(name: str, sql: str, values: dict) -> None:
        t_columns, t_rows, _ = store.query(sql, values)
        tables[name] = {"columns": t_columns, "rows": [list(r) for r in t_rows], "sql": sql.strip()}

    for name, sql in TABLES.items():
        add(name, sql, params)

    # Revenue (USD): its own run, champion and borough-day forecast, when there is one.
    revenue_run, revenue_evaluation = None, []
    try:
        r_columns, r_rows, _ = store.query(REVENUE_RUN_SQL, {})
    except psycopg.errors.UndefinedTable:  # forecasts made before the revenue target
        r_rows = []
    if r_rows:
        revenue_run = dict(zip(r_columns, r_rows[0], strict=True))
        r_params = {"run": revenue_run["run_id"], "month": params["month"]}
        e_columns, e_rows, _ = store.query(EVALUATION_SQL, r_params)
        revenue_evaluation = [dict(zip(e_columns, r, strict=True)) for r in e_rows]
        for name, sql in REVENUE_TABLES.items():
            add(name, sql, r_params)

    # Forecast against actual, when a month has been checked.
    try:
        for name, sql in CHECK_TABLES.items():
            add(name, sql, {})
    except psycopg.errors.UndefinedTable:  # no month checked yet
        for name in CHECK_TABLES:
            tables.pop(name, None)
    return {
        "available": True,
        "run": run,
        "evaluation": [dict(zip(ev_columns, r, strict=True)) for r in ev_rows],
        "revenue_run": revenue_run,
        "revenue_evaluation": revenue_evaluation,
        "tables": tables,
    }
