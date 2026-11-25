"""The shift planner: what a few pickup zones offer over a shift window, next month.

The user picks up to five zones, a day type (weekdays, weekends and holidays, or all days)
and a window of consecutive hours. For each zone the page shows:

- the expected trips and revenue in that window on a typical matching day of the forecast
  month (the published forecast, whichever method is the champion);
- the range of trips actually recorded in the same window over the last eight weeks
  (10th, 50th and 90th percentile of the days, empty days counted as zero);
- the average fare, duration and distance of a trip there, from the same recorded weeks;
- the rides demand in hours (expected trips x average duration): how many taxi-hours of
  paid rides the zone generates in the window, shared by every taxi working there.

It describes the opportunity of a zone, not what one taxi would earn: the data has no
taxi or driver identifier, so the share one driver gets is unknown. A window that runs
past midnight is read on the same calendar day (hours 22-23 and 0-1 of one date).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import psycopg

MAX_ZONES = 5
RECENT_DAYS = 56  # eight weeks of recorded trips for the range and the trip averages

# Day types on the calendar of analytics.dim_date: holidays go with the weekends.
DAY_FILTER = {
    "weekday": "NOT (d.is_weekend OR d.is_holiday)",
    "weekend": "(d.is_weekend OR d.is_holiday)",
    "all": "TRUE",
}

RUN_SQL = """
SELECT r.forecast_month, r.validated_month, r.champion,
       (SELECT champion FROM ml.current_revenue_run) AS revenue_champion
FROM ml.current_run AS r
"""
ZONES_SQL = """
SELECT zone_name, borough, min(demand_tier) AS demand_tier,
       sum(predicted_trips)::float AS predicted
FROM ml.current_forecast
GROUP BY zone_name, borough
ORDER BY predicted DESC
LIMIT 300"""
# Expected trips and revenue per zone and hour on a typical matching day of the forecast.
PROFILE_SQL = """
SELECT f.zone_name, f.borough, f.pickup_hour,
       avg(f.predicted_trips)::float AS trips, avg(f.lower_80)::float AS lower,
       avg(f.upper_80)::float AS upper, avg(r.predicted_usd)::float AS revenue,
       min(f.demand_tier) AS demand_tier, bool_or(f.low_confidence) AS low_confidence,
       count(DISTINCT f.date_day) AS days
FROM ml.current_forecast AS f
JOIN analytics.dim_date AS d ON d.date_day = f.date_day
LEFT JOIN ml.current_revenue_forecast AS r
  ON r.zone_sk = f.zone_sk AND r.date_day = f.date_day AND r.pickup_hour = f.pickup_hour
WHERE f.zone_name = ANY(%(zones)s::text[]) AND f.pickup_hour = ANY(%(hours)s::int[]) AND {days}
GROUP BY f.zone_name, f.borough, f.pickup_hour
ORDER BY f.zone_name, f.pickup_hour
LIMIT 300"""
# Other zones of the same boroughs, ranked on expected trips in the same window.
ALTERNATIVES_SQL = """
SELECT f.zone_name, f.borough,
       (sum(f.predicted_trips) / count(DISTINCT f.date_day))::float AS trips,
       (sum(r.predicted_usd) / count(DISTINCT f.date_day))::float AS revenue
FROM ml.current_forecast AS f
JOIN analytics.dim_date AS d ON d.date_day = f.date_day
LEFT JOIN ml.current_revenue_forecast AS r
  ON r.zone_sk = f.zone_sk AND r.date_day = f.date_day AND r.pickup_hour = f.pickup_hour
WHERE f.borough = ANY(%(boroughs)s::text[]) AND NOT f.zone_name = ANY(%(zones)s::text[])
  AND f.pickup_hour = ANY(%(hours)s::int[]) AND {days}
GROUP BY f.zone_name, f.borough
ORDER BY trips DESC
LIMIT 5"""
# Recorded valid trips in the window, per zone, day and hour, over the recent weeks.
HISTORY_SQL = """
SELECT d.pickup_zone AS zone_name, d.date_day::text AS date_day,
       sum(d.trip_count)::float AS trips, sum(d.sum_total_amount)::float AS amount,
       sum(d.sum_duration_min)::float AS minutes, sum(d.sum_trip_distance)::float AS miles
FROM analytics.mv_trips_hourly AS d
WHERE d.quality_status = 'valid' AND d.pickup_zone = ANY(%(zones)s::text[])
  AND d.pickup_hour = ANY(%(hours)s::int[])
  AND d.date_day > %(end)s::date - %(recent)s::int AND d.date_day <= %(end)s::date AND {days}
GROUP BY d.pickup_zone, d.date_day
ORDER BY d.pickup_zone, d.date_day
LIMIT 2000"""
# The matching days of the recent weeks, so a day without any trip counts as zero.
DAYS_SQL = """
SELECT count(*) AS days
FROM analytics.dim_date AS d
WHERE d.date_day > %(end)s::date - %(recent)s::int AND d.date_day <= %(end)s::date AND {days}"""


def window(start_hour: int, hours: int) -> list[int]:
    """The hours of a shift starting at start_hour, wrapping past midnight."""
    return [(start_hour + i) % 24 for i in range(hours)]


def month_end(month: str) -> date:
    year, number = (int(part) for part in month.split("-"))
    return date(year, number, calendar.monthrange(year, number)[1])


def _table(columns, rows, sql: str) -> dict:
    return {"columns": list(columns), "rows": [list(r) for r in rows], "sql": sql.strip()}


def _records(columns, rows) -> list[dict]:
    return [dict(zip(columns, r, strict=True)) for r in rows]


def zones(store) -> dict:
    """The zones of the published forecast, busiest first, for the zone picker."""
    try:
        columns, rows, _ = store.query(ZONES_SQL, {})
    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        return _table(["zone_name", "borough", "demand_tier", "predicted"], [], ZONES_SQL)
    return _table(columns, rows, ZONES_SQL)


def recent_range(daily: list[float], days: int) -> tuple[float, float, float] | None:
    """10th, 50th and 90th percentile of the window's trips per matching day, the days
    without a recorded trip counted as zero."""
    if days <= 0:
        return None
    values = sorted([0.0] * max(days - len(daily), 0) + list(daily))

    def percentile(q: float) -> float:  # linear interpolation between the closest ranks
        rank = q * (len(values) - 1)
        below = int(rank)
        above = min(below + 1, len(values) - 1)
        return values[below] + (values[above] - values[below]) * (rank - below)

    return percentile(0.1), percentile(0.5), percentile(0.9)


def summarise(profile: list[dict], history: list[dict], days: int) -> list[dict]:
    """One row per selected zone: forecast for the window and its recent record."""
    out = []
    for name in dict.fromkeys(row["zone_name"] for row in profile):
        hours = [row for row in profile if row["zone_name"] == name]
        recorded = [row for row in history if row["zone_name"] == name]
        trips = sum(row["trips"] for row in hours)
        revenues = [row["revenue"] for row in hours if row["revenue"] is not None]
        recorded_trips = sum(row["trips"] for row in recorded)

        def per_trip(column: str, rows=recorded, total=recorded_trips) -> float | None:
            return sum(row[column] for row in rows) / total if total > 0 else None

        minutes = per_trip("minutes")
        fare = per_trip("amount")
        spread = recent_range([row["trips"] for row in recorded], days)
        out.append(
            {
                "zone_name": name,
                "borough": hours[0]["borough"],
                "demand_tier": min(row["demand_tier"] for row in hours),
                "low_confidence": any(row["low_confidence"] for row in hours),
                "expected_trips": trips,
                "expected_revenue": sum(revenues) if len(revenues) == len(hours) else None,
                "recent_p10": spread[0] if spread else None,
                "recent_median": spread[1] if spread else None,
                "recent_p90": spread[2] if spread else None,
                "recorded_trips": recorded_trips,
                "fare_per_trip": fare,
                "minutes_per_trip": minutes,
                "miles_per_trip": per_trip("miles"),
                "ride_hours": trips * minutes / 60 if minutes is not None else None,
                "fare_per_ride_hour": fare / (minutes / 60) if fare and minutes else None,
            }
        )
    return sorted(out, key=lambda row: row["expected_trips"], reverse=True)


def plan(store, zone_names: list[str], day_type: str, start_hour: int, hours: int) -> dict:
    """The planner's answer for the chosen zones, day type and window."""
    if day_type not in DAY_FILTER:
        raise ValueError(f"unknown day type {day_type!r}")
    try:
        columns, rows, _ = store.query(RUN_SQL, {})
    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
        return {"available": False, "message": "No forecast yet: run the demand forecast job."}
    if not rows:
        return {"available": False, "message": "No published forecast yet."}
    run = dict(zip(columns, rows[0], strict=True))
    chosen = list(dict.fromkeys(zone_names))[:MAX_ZONES]
    span = window(start_hour, hours)
    days = DAY_FILTER[day_type]
    end = month_end(run["validated_month"]).isoformat()
    params = {"zones": chosen, "hours": span, "end": end, "recent": RECENT_DAYS}

    profile_sql = PROFILE_SQL.format(days=days)
    p_columns, p_rows, _ = store.query(profile_sql, params)
    profile = _records(p_columns, p_rows)
    boroughs = sorted({row["borough"] for row in profile})

    alternatives_sql = ALTERNATIVES_SQL.format(days=days)
    a_columns, a_rows, _ = store.query(alternatives_sql, {**params, "boroughs": boroughs})
    history_sql = HISTORY_SQL.format(days=days)  # the view carries is_weekend and is_holiday
    h_columns, h_rows, _ = store.query(history_sql, params)
    days_sql = DAYS_SQL.format(days=days)
    _, d_rows, _ = store.query(days_sql, params)
    matching_days = int(d_rows[0][0]) if d_rows else 0

    found = {row["zone_name"] for row in profile}
    return {
        "available": True,
        "forecast_month": run["forecast_month"],
        "recent_from": (date.fromisoformat(end) - timedelta(days=RECENT_DAYS - 1)).isoformat(),
        "recent_to": end,
        "recent_days": matching_days,
        "champion": run["champion"],
        "revenue_champion": run["revenue_champion"],
        "day_type": day_type,
        "hours": span,
        "unknown_zones": [name for name in chosen if name not in found],
        "zones": summarise(profile, _records(h_columns, h_rows), matching_days),
        "tables": {
            "profile": _table(p_columns, p_rows, profile_sql),
            "alternatives": _table(a_columns, a_rows, alternatives_sql),
            "history": _table(h_columns, h_rows, history_sql),
        },
    }
