"""The Overview page: the key figures of the latest published month, without the model.

Every figure goes through the same governed path as an answer of the assistant: a plan
of governed measures, validated against the catalogue, run with an approved SQL template
on the published layer with the read-only role. Only the language model is left out, so
the page shows the same numbers as the assistant and the dashboards, instantly. The
result is kept per publication: a new publication computes it again.
"""

from __future__ import annotations

import threading

from assistant.resolver import build, pivot_comparison, render
from assistant.schemas import DateRange, Intent, Period, QueryPlan
from assistant.validator import validate

LATEST = DateRange(period=Period.latest_month)

PLANS: dict[str, QueryPlan] = {
    # The month against the month before, for the headline figures.
    "kpis": QueryPlan(
        intent=Intent.lookup,
        metrics=["trips", "total_revenue", "avg_fare", "tip_rate"],
        date_range=LATEST,
        compare_to="previous_period",
    ),
    "trend": QueryPlan(
        intent=Intent.trend,
        metrics=["trips", "total_revenue"],
        grain="month",
        date_range=DateRange(period=Period.all_months),
    ),
    "boroughs": QueryPlan(
        intent=Intent.breakdown,
        metrics=["trips"],
        dimensions=["pickup_borough"],
        date_range=LATEST,
        limit=10,
    ),
    "zones": QueryPlan(
        intent=Intent.rank,
        metrics=["trips"],
        dimensions=["pickup_zone"],
        date_range=LATEST,
        order="desc",
        limit=8,
    ),
    "hourly": QueryPlan(
        intent=Intent.trend,
        metrics=["trips"],
        grain="hour",
        date_range=LATEST,
    ),
}

_cache: dict[str, dict] = {}
_lock = threading.Lock()


def compute(assistant) -> dict:
    """The page's tables, from the governed path (see the module docstring)."""
    catalog = assistant.catalog()
    with _lock:
        if catalog.published_run in _cache:
            return _cache[catalog.published_run]
    tables: dict[str, dict] = {}
    months: dict[str, list[str]] = {}
    for name, plan in PLANS.items():
        resolved = validate(plan.model_copy(deep=True), catalog)
        built = build(resolved, catalog, assistant.settings.max_rows)
        columns, rows, _ = assistant.store.query(built.sql, built.params)
        rows = [list(r) for r in rows]
        if built.kind == "compare":
            columns, rows = pivot_comparison(
                columns, rows, plan.dimensions, plan.metrics, plan.order, plan.limit
            )
        tables[name] = {"columns": columns, "rows": rows, "sql": render(built.sql, built.params)}
        months[name] = resolved.months + resolved.comparison_months
    latest = PLANS["kpis"]
    current = months["kpis"][0] if months["kpis"] else None
    previous = months["kpis"][1] if len(months["kpis"]) > 1 else None
    result = {
        "latest_month": current,
        "previous_month": previous,
        "published_run": catalog.published_run,
        "published_at": catalog.published_at,
        "valid_trip_rate": assistant.store.valid_trip_rate([current]) if current else None,
        "previous_valid_trip_rate": (
            assistant.store.valid_trip_rate([previous]) if previous else None
        ),
        "measures": {m: catalog.metrics[m]["label"] for m in latest.metrics},
        "tables": tables,
    }
    with _lock:
        _cache.clear()  # only the current publication is kept
        _cache[catalog.published_run] = result
    return result
