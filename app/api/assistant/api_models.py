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


class Rejection(Contract):
    """Body of a 422: the request was refused, with the reasons."""

    status: Literal["rejected"]
    reasons: list[str]
