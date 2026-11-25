"""Response models of the HTTP API: they are the OpenAPI contract the web interface's
TypeScript types are generated from (app/web, `npm run types`), so no type is written
twice by hand."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from assistant.schemas import Contract, Filter, QueryPlan


class WarmUp(Contract):
    state: str
    step_ms: dict[str, int] = Field(default_factory=dict)


class Health(Contract):
    status: Literal["ok", "degraded"]
    database: str
    model: str
    model_available: bool
    output_mode: str
    retrieval: bool
    prompt_cache_warm_up: WarmUp
    complete_months: list[str]


class MetricInfo(Contract):
    label: str
    description: str
    unit: str
    base_table: str
    sql_expression: str
    filters: str
    is_estimate: bool


class DimensionInfo(Contract):
    label: str
    members: list[str]


class CatalogView(Contract):
    metrics: dict[str, MetricInfo]
    dimensions: dict[str, DimensionInfo]
    complete_months: list[str]
    published_run: str
    published_at: str


class SessionCreated(Contract):
    session_id: str


class SessionReset(Contract):
    session_id: str
    active_filters: list[Filter]
    status: str


class SessionState(Contract):
    session_id: str
    turns: int
    active_filters: list[Filter]
    last_plan: QueryPlan | None


class ReportPreview(Contract):
    title: str
    chart: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    sql: str


class ReportView(Contract):
    report_id: str
    status: Literal["draft", "published"]
    dashboard_title: str
    dashboard_id: int
    dashboard_url: str
    chart_ids: list[int]
    specification: dict[str, Any]
    preview: list[ReportPreview]
    next_step: str


class OverviewTable(Contract):
    columns: list[str]
    rows: list[list[Any]]
    sql: str


class OverviewView(Contract):
    """Key figures of the latest published month, from the governed path without the model."""

    latest_month: str | None
    previous_month: str | None
    published_run: str
    published_at: str
    valid_trip_rate: float | None
    previous_valid_trip_rate: float | None
    measures: dict[str, str]  # headline measures and their labels
    tables: dict[str, OverviewTable]  # kpis, trend, boroughs, zones, hourly


class ForecastRun(Contract):
    run_id: str  # MLflow run id
    data_run: str  # publication the model was trained on
    created_at: str
    history_months: list[str]
    validated_month: str
    forecast_month: str
    model: str
    rounds: int
    wmape: float | None
    baseline_wmape: float | None
    champion: str  # method in service: "baseline" or "model"
    decision: str | None  # why, from the backtests


class ForecastScore(Contract):
    segment_type: str  # overall, borough, tier, borough_day
    segment: str
    rows: int
    actual_trips: float
    mae: float | None
    wmape: float | None
    bias: float | None
    baseline_mae: float | None
    baseline_wmape: float | None
    coverage_80: float | None


class ForecastView(Contract):
    """The published demand forecast (an estimate, never a governed measure)."""

    available: bool
    message: str | None = None
    run: ForecastRun | None = None
    evaluation: list[ForecastScore] = Field(default_factory=list)
    # The revenue forecast (USD): its own run and champion; actual_trips holds USD there.
    revenue_run: ForecastRun | None = None
    revenue_evaluation: list[ForecastScore] = Field(default_factory=list)
    # backtests, daily, zones, hourly, last_actual; revenue_daily, revenue_last_actual
    tables: dict[str, OverviewTable] = Field(default_factory=dict)


class PlannerZone(Contract):
    """One zone over the chosen window: forecast for a typical matching day of next month,
    and what was recorded there over the recent weeks."""

    zone_name: str
    borough: str
    demand_tier: str
    low_confidence: bool
    expected_trips: float
    expected_revenue: float | None  # USD; None without a revenue forecast
    recent_p10: float | None  # trips in the window per matching day, recent weeks
    recent_median: float | None
    recent_p90: float | None
    recorded_trips: float
    fare_per_trip: float | None  # USD, total amount
    minutes_per_trip: float | None
    miles_per_trip: float | None
    ride_hours: float | None  # expected trips x minutes per trip: paid ride time demanded
    fare_per_ride_hour: float | None  # USD per hour with a passenger (idle time excluded)


class PlannerView(Contract):
    """Zone opportunity over a shift window (an estimate, not one taxi's earnings)."""

    available: bool
    message: str | None = None
    forecast_month: str | None = None
    recent_from: str | None = None
    recent_to: str | None = None
    recent_days: int = 0
    champion: str | None = None
    revenue_champion: str | None = None
    day_type: str | None = None
    hours: list[int] = Field(default_factory=list)
    unknown_zones: list[str] = Field(default_factory=list)
    zones: list[PlannerZone] = Field(default_factory=list)
    tables: dict[str, OverviewTable] = Field(default_factory=dict)  # profile, alternatives, history


class Rejection(Contract):
    """Body of a 422: the request was refused, with the reasons."""

    status: Literal["rejected"]
    reasons: list[str]
