"""Questions about next month, answered from the published forecast (never by the model).

A forecast is an estimate: it lives in the ml schema, apart from the governed measures, and
its answers say so. The route is deterministic, like the guards:

1. Detection: forecast words ("forecast", "expected", "next month", "will"...) with a
   measure or a place named, or the forecast month itself named ("June 2025"). A question
   naming a published month or "last month" stays on the governed path.
2. Scope from the question: borough and zone (the vocabulary linker of the governed path),
   a breakdown ("by zone", "which hours", "each day"), hours ("8am", "between 7 and 9"),
   weekdays or weekends, "top N", busiest or quietest.
3. A fixed SQL shape on ml.current_forecast (or the revenue forecast), every value a
   parameter, read as ai_reader.
4. The text is written by code from the result: the 80 % range is given only where it is
   valid (one borough and one day); a total of days or hours has none, since the ranges of
   single days cannot be added up.

Only trips and revenue are forecast; a forecast question about another measure is answered
with what is available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date

import psycopg

from assistant.catalog import Catalog
from assistant.grounding import METRIC_WORDS, named_period
from assistant.guards import format_value
from assistant.retrieval import link_values
from assistant.schemas import DateRange, Filter, Intent, Operator, Period, QueryPlan

FORECAST_WORDS = re.compile(
    r"\b(forecasts?|forecasted|predict\w*|projections?|projected|expect(ed|s)?|next month|"
    r"upcoming|coming month|will|anticipat\w*)\b"
)
REVENUE_WORDS = re.compile(r"\b(revenue|income|money|takings|sales|turnover|paid|dollars?|usd)\b")
TRIP_WORDS = re.compile(r"\b(trips?|rides?|pickups?|demand|volume|busy|busiest|quiet\w*)\b")
OTHER_MEASURES = re.compile(
    r"\b(fares?|tips?|tip rate|distance|duration|miles?|co2|emissions?|congestion|"
    r"airport fees?|quality|valid trips?|passengers?|speed)\b"
)
QUIET = re.compile(r"\b(quiet\w*|least|lowest|fewest|slowest|bottom)\b")
WEEKEND = re.compile(r"\b(weekends?|saturdays?|sundays?|holidays?)\b")
WEEKDAY = re.compile(r"\b(weekdays?|working days?|business days?|week days?)\b")
BREAKDOWN = [  # first match wins
    ("pickup_zone", r"\b(zones?|neighbou?rhoods?|areas?|where)\b"),
    ("pickup_borough", r"\b(by|per|each|every|which|what|top|busiest|quiet\w*|rank\w*) boroughs?\b"
                       r"|\bboroughs\b"),
    ("pickup_hour", r"\b(hourly|by hour|per hour|each hour|which hours?|what time|times? of "
                    r"(the )?day|busiest hours?|quietest hours?|hour by hour)\b"),
    ("day", r"\b(daily|by day|per day|each day|every day|day by day|which days?|busiest days?|"
            r"quietest days?)\b"),
]  # fmt: skip
HOUR = r"(\d{1,2})(?::00)?\s*(am|pm|h)?"

RUN_SQL = """
SELECT run_id, data_run, created_at::text AS created_at, history_months, forecast_month,
       champion
FROM ml.current_run"""
REVENUE_RUN_SQL = RUN_SQL.replace("ml.current_run", "ml.current_revenue_run")
ACCURACY_SQL = """
SELECT avg(wmape)::float AS wmape, count(*) AS months
FROM ml.forecast_backtest
WHERE run_id = %(run)s AND method = %(method)s AND segment_type = 'borough_day'
  AND segment = 'all'"""

# Per target: zone x day x hour relation and value, borough x day relation and value.
SOURCES = {
    "trips": ("ml.current_forecast", "predicted_trips", "ml.current_forecast_daily"),
    "revenue": (
        "ml.current_revenue_forecast",
        "predicted_usd",
        "ml.current_revenue_forecast_daily",
    ),
}
METRIC = {"trips": "trips", "revenue": "total_revenue"}
COLUMN = {
    "pickup_borough": "f.borough",
    "pickup_zone": "f.zone_name",
    "pickup_hour": "f.pickup_hour",
}
DAY_FILTER = {
    "weekday": "NOT (d.is_weekend OR d.is_holiday)",
    "weekend": "(d.is_weekend OR d.is_holiday)",
}
DAY_TEXT = {"weekday": "weekdays", "weekend": "weekends and holidays"}


@dataclass
class ForecastAsk:
    """The scope of a forecast question, read from its words."""

    target: str = "trips"  # trips | revenue
    by: str | None = None  # pickup_borough | pickup_zone | pickup_hour | day
    boroughs: list[str] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    hours: list[int] = field(default_factory=list)
    day_type: str | None = None  # weekday | weekend
    quiet: bool = False
    limit: int = 10


@dataclass
class ForecastResult:
    plan: QueryPlan
    columns: list[str]
    rows: list[list]
    narrative: str
    limitations: list[str]
    sql: str
    params: dict
    run: dict


class NoForecast(Exception):
    """No forecast is published (job not run yet, or ml schema missing)."""


# ------------------------------------------------------------------ reading the question
def _hour(number: str, suffix: str | None) -> int | None:
    value = int(number)
    if suffix == "pm" and value < 12:
        value += 12
    elif suffix == "am" and value == 12:
        value = 0
    return value if 0 <= value <= 23 else None


def hours_named(question: str) -> list[int]:
    """Hours the question names: "at 8am", "8:00", "between 7 and 10am" (end excluded)."""
    text = question.lower()
    span = re.search(rf"\b(?:between|from)\s+{HOUR}\s*(?:and|to|-|until)\s+{HOUR}", text)
    if span:
        end_suffix = span.group(4)
        start = _hour(span.group(1), span.group(2) or end_suffix)
        end = _hour(span.group(3), end_suffix)
        if start is not None and end is not None and start != end:
            return [(start + i) % 24 for i in range((end - start) % 24)]
    found = []
    for number, suffix in re.findall(r"\b(\d{1,2})(?::00)?\s*(am|pm)\b", text) + re.findall(
        r"\b(\d{1,2}):00\b()", text
    ):
        hour = _hour(number, suffix or None)
        if hour is not None and hour not in found:
            found.append(hour)
    if re.search(r"\bmidnight\b", text) and 0 not in found:
        found.append(0)
    if re.search(r"\bnoon\b", text) and 12 not in found:
        found.append(12)
    return found


def read(question: str, catalog: Catalog) -> ForecastAsk:
    text = question.lower()
    links = link_values(question, catalog)
    ask = ForecastAsk(
        target="revenue" if REVENUE_WORDS.search(text) else "trips",
        boroughs=[link.value for link in links if link.dimension == "pickup_borough"],
        zones=[link.value for link in links if link.dimension == "pickup_zone"],
        hours=hours_named(question),
        day_type="weekend" if WEEKEND.search(text) else "weekday" if WEEKDAY.search(text) else None,
        quiet=QUIET.search(text) is not None,
    )
    for by, pattern in BREAKDOWN:
        if re.search(pattern, text):
            ask.by = by
            break
    if ask.by == "pickup_zone" and len(ask.zones) == 1 and not re.search(r"\bzones\b", text):
        ask.by = None  # "at JFK Airport": one named zone, not a ranking of zones
    if ask.by == "pickup_borough" and len(ask.boroughs) == 1:
        ask.by = None
    top = re.search(r"\b(?:top|first|bottom)\s+(\d{1,2})\b", text)
    if top:
        ask.limit = max(1, min(int(top.group(1)), 50))
    return ask


def follow_up(question: str, previous: ForecastAsk, catalog: Catalog) -> ForecastAsk:
    """A short follow-up ("and for Queens?", "by hour?") changes what it names only."""
    new = read(question, catalog)
    ask = replace(previous)
    if new.boroughs or new.zones:
        ask.boroughs, ask.zones = new.boroughs, new.zones
    if REVENUE_WORDS.search(question.lower()) or TRIP_WORDS.search(question.lower()):
        ask.target = new.target
    for name in ("by", "day_type"):
        if getattr(new, name):
            setattr(ask, name, getattr(new, name))
    if new.hours:
        ask.hours = new.hours
    return ask


def wants_forecast(question: str, catalog: Catalog) -> bool:
    """Forecast words with a measure or a place, or a month after the published ones."""
    text = question.lower()
    named = named_period(question)
    if named is not None:
        if named.period != Period.custom or not catalog.months:
            return False  # "last month", "this month": the governed path
        return named.start_month > catalog.months[-1]
    if not FORECAST_WORDS.search(text):
        return False
    return bool(re.search(METRIC_WORDS, text) or TRIP_WORDS.search(text)
                or REVENUE_WORDS.search(text) or link_values(question, catalog))  # fmt: skip


def is_follow_up(question: str) -> bool:
    """Short, names no measure and no period: it continues the previous answer."""
    text = question.lower()
    return (
        len(text) <= 80
        and named_period(question) is None
        and re.search(METRIC_WORDS, text) is None
        and REVENUE_WORDS.search(text) is None
    )


# "How accurate was the May forecast?": answered from the forecast-against-actual checks.
ACCURACY_WORDS = re.compile(
    r"\b(accura\w*|how (good|well|close|far off)|error|miss\w*|wrong|right|off by|drift)\b"
)
FORECAST_NOUNS = re.compile(r"\b(forecasts?|predict\w*|projections?|estimates?)\b")
CHECK_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (target, month) *
    FROM ml.forecast_check_run
    WHERE target = %(target)s
    ORDER BY target, month, (actual_wmape IS NULL OR actual_wmape = 'NaN'), replay,
             checked_at DESC
)
SELECT l.month, l.method, l.replay, l.status, l.expected_wmape::float AS expected,
       s.segment AS pickup_borough, s.wmape::float AS forecast_error,
       s.bias::float AS forecast_bias, s.coverage_80::float AS coverage,
       s.predicted::float AS forecast, s.actual::float AS recorded
FROM latest AS l JOIN ml.forecast_check AS s USING (run_id)
WHERE s.segment_type = 'borough_day'
  AND l.month = coalesce(%(month)s, (SELECT max(month) FROM latest))
ORDER BY s.segment = 'all' DESC, s.wmape DESC
LIMIT 12"""


def wants_accuracy(question: str) -> bool:
    text = question.lower()
    return bool(ACCURACY_WORDS.search(text) and FORECAST_NOUNS.search(text))


def accuracy_month(question: str) -> str | None:
    """The month the question names ("May 2025", "2025-05", "May"), else None: the latest
    month checked."""
    named = named_period(question)
    if named is not None and named.period == Period.custom:
        return named.start_month
    text = question.lower()
    for name, number in (("january", 1), ("february", 2), ("march", 3), ("april", 4),
                         ("may", 5), ("june", 6), ("july", 7), ("august", 8),
                         ("september", 9), ("october", 10), ("november", 11),
                         ("december", 12)):  # fmt: skip
        if re.search(rf"\b{name}\b", text):
            return f"%-{number:02d}"  # a month name alone: its latest year, resolved below
    return None


def accuracy(store, question: str, target: str) -> tuple[list[str], list[list], str, dict]:
    """(columns, rows, narrative, run facts) of the check of the month asked; rows are the
    boroughs, the first one the whole city."""
    month = accuracy_month(question)
    if month and month.startswith("%"):  # month name without a year: the latest such month
        _, found, _ = store.query(
            "SELECT max(month) FROM ml.forecast_check_run WHERE target = %(t)s "
            "AND month LIKE %(m)s",
            {"t": target, "m": month},
        )
        month = found[0][0] if found and found[0][0] else None
    columns, rows, _ = store.query(CHECK_SQL, {"target": target, "month": month})
    if not rows:
        return [], [], "", {}
    data = [dict(zip(columns, r, strict=True)) for r in rows]
    city = next((d for d in data if d["pickup_borough"] == "all"), data[0])
    worst = [d for d in data if d["pickup_borough"] != "all"][:3]
    method = {"model": "the LightGBM model", "adjusted": "the adjusted baseline"}.get(
        city["method"], "the seasonal baseline"
    )
    bias = city["forecast_bias"] or 0.0
    text = (
        f"The forecast of {_month(city['month'])} ({method}"
        f"{', replayed as at the time' if city['replay'] else ''}) missed by "
        f"{city['forecast_error'] * 100:.1f} % per borough and day, against "
        f"{city['expected'] * 100:.1f} % promised by its backtests: "
        f"{'flagged as drift' if city['status'] == 'drift' else 'as expected'}. Overall it was "
        f"{abs(bias) * 100:.1f} % too {'low' if bias < 0 else 'high'}, and "
        f"{city['coverage'] * 100:.0f} % of the borough-days fell inside its 80 % range. "
        "Largest errors: "
        + ", ".join(f"{d['pickup_borough']} ({d['forecast_error'] * 100:.1f} %)" for d in worst)
        + "."
    )
    out_columns = ["pickup_borough", "forecast_error", "forecast_bias", "forecast", "recorded"]
    out_rows = [
        ["All boroughs" if d["pickup_borough"] == "all" else d["pickup_borough"],
         round(d["forecast_error"], 4), round(d["forecast_bias"] or 0, 4),
         round(d["forecast"]), round(d["recorded"])]
        for d in data
    ]  # fmt: skip
    return out_columns, out_rows, text, {"month": city["month"], "sql": CHECK_SQL.strip()}


def names_scope(ask: ForecastAsk) -> bool:
    """Does a follow-up name something to change? ("thanks" does not)."""
    return bool(ask.boroughs or ask.zones or ask.by or ask.hours or ask.day_type)


def shown_sql(sql: str, params: dict) -> str:
    """SQL with its parameters inline, for the provenance and the audit log only."""

    def literal(value) -> str:
        if isinstance(value, list):
            return "ARRAY[" + ", ".join(literal(v) for v in value) + "]"
        if isinstance(value, int):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    for key, value in params.items():
        sql = sql.replace(f"%({key})s", literal(value))
    return sql


def unforecast_measure(question: str) -> str | None:
    """A measure that is not forecast, asked without trips or revenue."""
    text = question.lower()
    other = OTHER_MEASURES.search(text)
    if other and not REVENUE_WORDS.search(text) and not re.search(r"\b(trips?|rides?)\b", text):
        return other.group(0)
    return None


# ------------------------------------------------------------------ the query
def _filters(ask: ForecastAsk, params: dict) -> list[str]:
    where = []
    if ask.boroughs:
        params["boroughs"] = ask.boroughs
        where.append("f.borough = ANY(%(boroughs)s::text[])")
    if ask.zones:
        params["zones"] = ask.zones
        where.append("f.zone_name = ANY(%(zones)s::text[])")
    if ask.hours:
        params["hours"] = ask.hours
        where.append("f.pickup_hour = ANY(%(hours)s::int[])")
    if ask.day_type:
        where.append(DAY_FILTER[ask.day_type])
    return where


def build(ask: ForecastAsk) -> tuple[str, dict, list[str], bool]:
    """(sql, params, columns, with_range). Column names follow the governed measure
    ("trips", "total_revenue") so the interface shows them like any answer."""
    detail, value, daily = SOURCES[ask.target]
    metric = METRIC[ask.target]
    params: dict = {}
    # One borough (or each borough) per day, no zone or hour: the borough-day forecast has a
    # valid 80 % range.
    if ask.by == "day" and not ask.zones and not ask.hours and len(ask.boroughs) == 1:
        where = ["f.borough = %(borough)s"] + ([DAY_FILTER[ask.day_type]] if ask.day_type else [])
        params["borough"] = ask.boroughs[0]
        sql = f"""
SELECT f.date_day::text AS period, f.{value}::float AS {metric},
       f.lower_80::float AS {metric}_low_80, f.upper_80::float AS {metric}_high_80
FROM {daily} AS f
JOIN analytics.dim_date AS d ON d.date_day = f.date_day
WHERE {" AND ".join(where)}
ORDER BY f.date_day
LIMIT 31"""
        return sql, params, ["period", metric, f"{metric}_low_80", f"{metric}_high_80"], True

    where = _filters(ask, params) or ["TRUE"]
    joins = f"FROM {detail} AS f\nJOIN analytics.dim_date AS d ON d.date_day = f.date_day"
    days = "count(DISTINCT f.date_day)"
    if ask.by is None:
        sql = f"""
SELECT sum(f.{value})::float AS {metric}, (sum(f.{value}) / {days})::float AS {metric}_per_day
{joins}
WHERE {" AND ".join(where)}
LIMIT 1"""
        return sql, params, [metric, f"{metric}_per_day"], False
    if ask.by == "day":
        sql = f"""
SELECT f.date_day::text AS period, sum(f.{value})::float AS {metric}
{joins}
WHERE {" AND ".join(where)}
GROUP BY f.date_day
ORDER BY f.date_day
LIMIT 31"""
        return sql, params, ["period", metric], False
    if ask.by == "pickup_hour":  # on an average day of the month
        sql = f"""
SELECT f.pickup_hour, (sum(f.{value}) / {days})::float AS {metric}
{joins}
WHERE {" AND ".join(where)}
GROUP BY f.pickup_hour
ORDER BY f.pickup_hour
LIMIT 24"""
        return sql, params, ["pickup_hour", metric], False
    column = COLUMN[ask.by]
    order = "ASC" if ask.quiet else "DESC"
    params["limit"] = ask.limit
    sql = f"""
SELECT {column} AS {ask.by}, sum(f.{value})::float AS {metric}
{joins}
WHERE {" AND ".join(where)}
GROUP BY {column}
ORDER BY {metric} {order}
LIMIT %(limit)s"""
    return sql, params, [ask.by, metric], False


# ------------------------------------------------------------------ the answer
def _month(month: str) -> str:
    year, number = month.split("-")
    return date(int(year), int(number), 1).strftime("%B %Y")


def _round(value):
    if not isinstance(value, float):
        return value
    return round(value) if abs(value) >= 100 else round(value, 1)


def scope_text(ask: ForecastAsk) -> str:
    parts = []
    if ask.zones:
        parts.append("at " + ", ".join(ask.zones))
    if ask.boroughs:
        parts.append("in " + ", ".join(ask.boroughs))
    if ask.day_type:
        parts.append("on " + DAY_TEXT[ask.day_type])
    if ask.hours:
        first, last = ask.hours[0], (ask.hours[-1] + 1) % 24
        contiguous = all((b - a) % 24 == 1 for a, b in zip(ask.hours, ask.hours[1:], strict=False))
        parts.append(
            f"from {first:02d}:00 to {last:02d}:00"
            if contiguous and len(ask.hours) > 1
            else "at " + ", ".join(f"{h:02d}:00" for h in ask.hours)
        )
    return (" " + ", ".join(parts)) if parts else ""


def narrative(ask: ForecastAsk, columns, rows, run: dict, accuracy: dict, unit: str) -> str:
    month = _month(run["forecast_month"])
    scope = scope_text(ask)
    noun = "trips" if ask.target == "trips" else "of revenue (total paid)"

    def fmt(value: float) -> str:
        return formatted(value, ask.target, unit)

    data = [dict(zip(columns, r, strict=True)) for r in rows]
    metric = METRIC[ask.target]
    if ask.by is None:
        row = data[0]
        text = (
            f"Estimate for {month}: about {fmt(row[metric])} {noun} expected{scope}, "
            f"{fmt(row[f'{metric}_per_day'])} a day on average."
        )
    elif ask.by in ("pickup_zone", "pickup_borough"):
        kind = "pickup zones" if ask.by == "pickup_zone" else "boroughs"
        listed = ", ".join(f"{r[ask.by]} ({fmt(r[metric])})" for r in data[:5])
        text = (
            f"Estimate for {month}{scope}: the {'quietest' if ask.quiet else 'busiest'} {kind} "
            f"expected are {listed}, {noun} over the month."
        )
    elif ask.by == "pickup_hour":
        peak = max(data, key=lambda r: r[metric])
        low = min(data, key=lambda r: r[metric])
        text = (
            f"Estimate for {month}{scope}, on an average day: the busiest hour is "
            f"{peak['pickup_hour']:02d}:00 with {fmt(peak[metric])} {noun}, the quietest "
            f"{low['pickup_hour']:02d}:00 with {fmt(low[metric])}."
        )
    else:  # by day
        peak = max(data, key=lambda r: r[metric])
        low = min(data, key=lambda r: r[metric])
        day = date.fromisoformat(peak["period"]).strftime("%A %d %B")
        text = (
            f"Estimate for {month}{scope}: from {fmt(low[metric])} to {fmt(peak[metric])} {noun} "
            f"a day; the busiest day expected is {day} ({fmt(peak[metric])}"
        )
        if f"{metric}_low_80" in peak:
            text += (
                f", 80 % range {fmt(peak[f'{metric}_low_80'])} to {fmt(peak[f'{metric}_high_80'])}"
            )
        text += ")."
    return f"{text} This is an estimate, not a measured figure."  # method: in the limits


def method_note(run: dict, accuracy: dict) -> str:
    """Which method made the forecast and how it did on the months before."""
    method = {
        "model": "the LightGBM model",
        "adjusted": "the adjusted baseline (recent trend and last year's seasonality)",
    }.get(run["champion"], "the seasonal baseline")
    text = f"Forecast made by {method}, the method in service"
    if accuracy.get("wmape") is not None:
        text += (
            f"; over its last {accuracy['months']} test months its error per borough and day "
            f"averaged {accuracy['wmape'] * 100:.1f} %"
        )
    return text + "."


def formatted(value, target: str, unit: str) -> str:
    """3,336,971 (trips); 84.2 (trips); 987,091 USD."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return str(value)
    if target == "revenue":
        return format_value(value, unit)
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}".removesuffix(".0")


ESTIMATE_WORDS = re.compile(
    r"\b(expect\w*|estimat\w*|forecast\w*|predict\w*|projected|likely|anticipat\w*|will|"
    r"next month)\b",
    re.IGNORECASE,
)
LABELS = {
    "pickup_zone": "Pickup zone",
    "pickup_borough": "Pickup borough",
    "pickup_hour": "Pickup hour",
    "period": "Day",
}


def key_facts(ask: ForecastAsk, result: ForecastResult) -> tuple[str, list[float]]:
    """Facts computed by code for the narrator, already sorted and formatted, and the extra
    figures they quote (weekday averages), which the number check then accepts. Observed:
    reading a 24-row table, the model gave one hour's figure to another; reading 30 days,
    it called Mondays busy when they are the quietest."""
    metric = METRIC[ask.target]
    unit = "USD" if ask.target == "revenue" else "trips"

    def f(value) -> str:
        return formatted(value, ask.target, unit)

    data = [dict(zip(result.columns, r, strict=True)) for r in result.rows]
    ranked = sorted(data, key=lambda r: r[metric], reverse=True)
    facts, extra = (
        [result.narrative.removesuffix(" This is an estimate, not a measured figure.")],
        [],
    )
    if ask.by == "pickup_hour":
        facts.append(
            "Busiest hours, in order: "
            + ", ".join(f"{r['pickup_hour']:02d}:00 ({f(r[metric])})" for r in ranked[:5])
            + "."
        )
        facts.append(
            "Quietest hours: "
            + ", ".join(f"{r['pickup_hour']:02d}:00 ({f(r[metric])})" for r in ranked[-3:][::-1])
            + "."
        )
    elif ask.by == "day":

        def day(r) -> str:  # "Sunday 1 June"
            d = date.fromisoformat(r["period"])
            return f"{d:%A} {d.day} {d:%B}"

        facts.append(
            "Busiest days, in order: "
            + ", ".join(f"{day(r)} ({f(r[metric])})" for r in ranked[:3])
            + "."
        )
        facts.append(
            "Quietest days: "
            + ", ".join(f"{day(r)} ({f(r[metric])})" for r in ranked[-2:][::-1])
            + "."
        )
        by_weekday: dict[str, list[float]] = {}
        for r in data:
            name = date.fromisoformat(r["period"]).strftime("%A")
            by_weekday.setdefault(name, []).append(float(r[metric]))
        averages = {name: sum(v) / len(v) for name, v in by_weekday.items()}
        order = sorted(averages, key=averages.get, reverse=True)
        extra = [round(averages[name]) for name in order]
        facts.append(
            "Average per weekday, highest first: "
            + ", ".join(f"{name} {f(round(averages[name]))}" for name in order)
            + "."
        )
    elif ask.by in ("pickup_zone", "pickup_borough"):
        facts.append(
            "Ranking, expected over the month: "
            + "; ".join(f"{i}. {r[ask.by]} ({f(r[metric])})" for i, r in enumerate(data[:10], 1))
            + "."
        )
    return " ".join(facts), extra + [80.0]  # "80 % range"


def model_message(question: str, ask: ForecastAsk, result: ForecastResult, label: str) -> str:
    """The narrator's message for a forecast: the formatted result and what to write."""
    metric = METRIC[ask.target]
    heads = {
        metric: f"{label} expected",
        f"{metric}_per_day": f"{label} expected per day",
        f"{metric}_low_80": "80 % range, low",
        f"{metric}_high_80": "80 % range, high",
    }
    unit = "USD" if ask.target == "revenue" else "trips"

    def cell(column: str, value) -> str:
        if column == "pickup_hour":
            return f"{value:02d}:00"
        return formatted(value, ask.target, unit) if column.startswith(metric) else str(value)

    table = "\n".join(
        [" | ".join(heads.get(c, LABELS.get(c, c)) for c in result.columns)]
        + [
            " | ".join(cell(c, v) for c, v in zip(result.columns, r, strict=True))
            for r in result.rows
        ]  # fmt: skip
    )
    per = {"pickup_hour": " (per hour, on an average day)", "period": " (per day)"}
    return (
        f"QUESTION: {question}\n"
        f"METRICS: {label} ({unit}), FORECAST for next month: an estimate, not recorded data\n"
        f"PERIOD: {_month(result.run['forecast_month'])} (the forecast month)\n"
        f"FILTERS: {scope_text(ask).strip() or 'none'}\n"
        f"RESULT{per.get(ask.by or '', '' if ask.by else ' (whole month)')}:\n{table}\n\n"
        f"KEY FACTS (computed by code, correct; prefer them to reading the table): "
        f"{key_facts(ask, result)[0]}\n\n"
        "THIS IS A FORECAST of next month. Write the answer like any other (rules above): the "
        "direct answer first, with the key figure in **bold**, then what helps read it. A "
        "bullet list only for a ranking of several rows, never to repeat one or two figures. "
        "Word every figure as an estimate ('about ... are expected'), never as something that "
        "happened. Use only the figures of the KEY FACTS and the RESULT, each with its own "
        "zone, hour, day or weekday. One possible explanation is welcome, worded as a "
        "hypothesis, without numbers, about the pattern itself (time of day, day of the week, "
        "airports, nightlife, commuting), not about the economy."
    )


MONTH_WORDS = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
)
SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+|;\s*")  # sentences and clauses
MEMBER_COLUMN = {
    "pickup_zone": "pickup_zone",
    "pickup_borough": "pickup_borough",
    "pickup_hour": "pickup_hour",
    "day": "period",
}


JOINED = re.compile(r"^\s*(,|and|or|&|, and|, or)\s*$")  # "1st and 30th", "17:00, 18:00"


def mentions(sentence: str, ask: ForecastAsk, result: ForecastResult) -> list[tuple]:
    """(start, end, rows) of each zone, borough, hour or day the sentence names."""
    column = result.columns.index(MEMBER_COLUMN[ask.by])
    text = sentence.lower()
    found = []
    if ask.by in ("pickup_zone", "pickup_borough"):
        for i, r in enumerate(result.rows):
            for m in re.finditer(re.escape(str(r[column]).lower()), text):
                found.append((m.start(), m.end(), {i}))
        # The longest name at a place ("Upper East Side South", not "Upper East Side").
        found = [
            f for f in found
            if not any(g[0] <= f[0] and f[1] <= g[1] and g[1] - g[0] > f[1] - f[0] for g in found)
        ]  # fmt: skip
    elif ask.by == "pickup_hour":  # "17:00", "5 pm", "5:30pm"
        for m in re.finditer(r"\b(\d{1,2})(?::\d\d)?\s*(am|pm)\b|\b(\d{1,2}):\d\d\b", text):
            hour = _hour(m.group(1), m.group(2)) if m.group(1) else _hour(m.group(3), None)
            found.append((m.start(), m.end(), {i for i, r in enumerate(result.rows)
                                               if r[column] == hour}))  # fmt: skip
    else:
        patterns = [
            r"\b(\d{1,2})(?:st|nd|rd|th)\b",
            rf"\b{MONTH_WORDS}\s+(\d{{1,2}})\b",
            rf"\b(\d{{1,2}})\s+{MONTH_WORDS}\b",
            r"\b20\d\d-\d\d-(\d\d)\b",
        ]
        for pattern in patterns:
            for m in re.finditer(pattern, text):
                rows = {i for i, r in enumerate(result.rows)
                        if int(str(r[column])[-2:]) == int(m.group(1))}  # fmt: skip
                found.append((m.start(), m.end(), rows))
        found = [f for f in found if not any(g != f and g[0] <= f[0] and f[1] <= g[1]
                                             for g in found)]  # fmt: skip
    return sorted(found, key=lambda f: f[0])


def misattributed(text: str, ask: ForecastAsk, result: ForecastResult) -> list[str]:
    """A figure must belong to the zone, hour or day it is quoted with: the member nearest
    to it, and every member listed together with that one ("June 1st and 30th").
    Observed: "8,728 trips at the peak hour of 17:00" (8,728 is 18:00), "6,658 trips on
    June 1st and 30th" (only 1 June); the number check passes both. Accepted: "starts
    around 17:00 and peaks at 18:00, with about 8,728 trips"."""
    from assistant.guards import NUMBER, _matches, _numbers_in

    if ask.by is None:
        return []
    metric = METRIC[ask.target]
    own = [
        [float(v) for c, v in zip(result.columns, r, strict=True)
         if c.startswith(metric) and v is not None]
        for r in result.rows
    ]  # fmt: skip
    member = result.columns.index(MEMBER_COLUMN[ask.by])
    problems = []
    for sentence in SENTENCES.split(text):
        named = mentions(sentence, ask, result)
        if not named:
            continue
        groups, current = [], [named[0]]
        for previous, mention in zip(named, named[1:], strict=False):
            if JOINED.match(sentence.lower()[previous[1] : mention[0]]):
                current.append(mention)
            else:
                groups.append(current)
                current = [mention]
        groups.append(current)
        # "80 % range" is a label, not a figure; blanked so positions stay the same.
        blanked = re.sub(r"\b80\s*%", lambda m: " " * len(m.group(0)), sentence)
        for match in NUMBER.finditer(blanked):
            values = _numbers_in(match.group(0))
            if not values or (
                float(values[0]).is_integer() and (abs(values[0]) < 32 or 1990 <= values[0] <= 2100)
            ):
                continue  # fmt: skip
            n = values[0]
            if any(m[0] <= match.start() < m[1] for m in named):
                continue  # part of a member's name or time ("18:00")

            s, e = match.start(), match.end()
            nearest = min(named, key=lambda m, s=s, e=e: max(m[0] - e, s - m[1], 0))
            group = next(g for g in groups if nearest in g)
            for mention in group:
                if not any(_matches(n, own[i]) for i in mention[2]):
                    shown = ", ".join(str(result.rows[i][member]) for i in mention[2]) or "?"
                    problems.append(f"{n:g} quoted with {shown}, whose figure it is not")
    return problems


def check_model_text(text: str, ask: ForecastAsk, result: ForecastResult) -> str | None:
    """Why the model's text cannot be used, or None."""
    from assistant.guards import unsupported_numbers, wrong_rankings

    if not text:
        return "empty text"
    bad = unsupported_numbers(text, result.rows, allowed=key_facts(ask, result)[1])
    if bad:
        return "number(s) not in the result: " + ", ".join(f"{n:g}" for n in bad)
    wrong = wrong_rankings(text, result.columns, result.rows, METRIC[ask.target])
    if wrong:
        return "ranking contradicted by the result: " + "; ".join(wrong)
    wrong = misattributed(text, ask, result)
    if wrong:
        return "figure attributed to the wrong member: " + "; ".join(wrong[:3])
    if not ESTIMATE_WORDS.search(text):
        return "not worded as an estimate"
    return None


def plan_of(ask: ForecastAsk, month: str) -> QueryPlan:
    """The scope as a plan, shown with the answer like any other."""
    filters = []
    if ask.boroughs:
        filters.append(
            Filter(dimension="pickup_borough", operator=Operator.in_, values=ask.boroughs)
        )
    if ask.zones:
        filters.append(Filter(dimension="pickup_zone", operator=Operator.in_, values=ask.zones))
    if ask.hours:
        filters.append(Filter(dimension="pickup_hour", operator=Operator.in_, values=ask.hours))
    if ask.day_type:
        filters.append(Filter(dimension="day_type", values=[DAY_TEXT[ask.day_type]]))
    intent = {
        None: Intent.lookup,
        "pickup_zone": Intent.rank,
        "pickup_borough": Intent.rank,
        "pickup_hour": Intent.breakdown,
        "day": Intent.trend,
    }[ask.by]
    return QueryPlan(
        intent=intent,
        metrics=[METRIC[ask.target]],
        dimensions=[ask.by] if ask.by in COLUMN else [],
        filters=filters,
        date_range=DateRange(period=Period.custom, start_month=month, end_month=month),
        grain="day" if ask.by == "day" else "hour" if ask.by == "pickup_hour" else None,
        order="asc" if ask.quiet else "desc",
        limit=ask.limit,
    )


def run_of(store, target: str) -> dict:
    try:
        columns, rows, _ = store.query(RUN_SQL if target == "trips" else REVENUE_RUN_SQL, {})
    except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName) as exc:
        raise NoForecast("no forecast is published yet") from exc
    if not rows:
        raise NoForecast(f"no {target} forecast is published yet")
    return dict(zip(columns, rows[0], strict=True))


def answer(store, ask: ForecastAsk, run: dict, unit: str) -> ForecastResult:
    sql, params, _, with_range = build(ask)
    columns, rows, _ = store.query(sql, params)
    rows = [[_round(v) for v in r] for r in rows]
    a_columns, a_rows, _ = store.query(
        ACCURACY_SQL, {"run": run["run_id"], "method": run["champion"]}
    )
    accuracy = dict(zip(a_columns, a_rows[0], strict=True)) if a_rows else {}
    limitations = [
        "Estimate from the published forecast, not a measured figure. "
        + method_note(run, accuracy),
        "It forecasts recorded trips: demand that found no taxi leaves no trace in the data.",
    ]
    if not with_range:
        limitations.append(
            "No 80 % range for a total: the ranges of single days or hours cannot be added up. "
            "Ask for one borough day by day to see it."
        )
    if ask.hours:
        limitations.append("Hours are pickup hours of each day of the month.")
    plan = plan_of(ask, run["forecast_month"])
    has_rows = bool(rows) and rows[0][0] is not None
    text = narrative(ask, columns, rows, run, accuracy, unit) if has_rows else ""
    return ForecastResult(plan, list(columns), rows if has_rows else [], text, limitations,
                          sql.strip(), params, run)  # fmt: skip
