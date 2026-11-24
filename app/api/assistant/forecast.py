"""The Forecast page: the published demand forecast and how well its model did.

Fixed queries on the ml schema (written by the forecasting job, read here as ai_reader):
the latest published run, its evaluation against the seasonal naive baseline, the
forecast per borough and day with its 80 % interval, the busiest zones and the hourly
profile; plus the actual trips of the validated month for comparison. A forecast is an
estimate: it is never mixed with the governed measures.
"""

from __future__ import annotations

import psycopg

RUN_SQL = """
SELECT run_id, data_run, created_at::text, history_months, validated_month, forecast_month,
       model, rounds, wmape::float, baseline_wmape::float
FROM ml.current_run
"""
EVALUATION_SQL = """
SELECT segment_type, segment, rows, actual_trips::float, mae::float, wmape::float, bias::float,
       baseline_mae::float, baseline_wmape::float, coverage_80::float
FROM ml.forecast_evaluation WHERE run_id = %(run)s
ORDER BY segment_type, actual_trips DESC
"""
TABLES = {
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
    for name, sql in TABLES.items():
        t_columns, t_rows, _ = store.query(sql, params)
        tables[name] = {"columns": t_columns, "rows": [list(r) for r in t_rows], "sql": sql.strip()}
    return {
        "available": True,
        "run": run,
        "evaluation": [dict(zip(ev_columns, r, strict=True)) for r in ev_rows],
        "tables": tables,
    }
