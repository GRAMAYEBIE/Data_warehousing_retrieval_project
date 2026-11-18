"""Structured contracts between the LLM, the validator, the resolver and the user.

The LLM never returns SQL or numbers: it returns a QueryPlan (or a ReportRequest), which
is validated against the governed catalogue before anything touches the database.
Relative periods are words ("last_month"), resolved to dates by code, not by the model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Intent(StrEnum):
    trend = "trend"  # a metric over time
    compare = "compare"  # a period versus another period
    rank = "rank"  # top or bottom N members of a dimension
    breakdown = "breakdown"  # a metric split by a dimension
    lookup = "lookup"  # one value
    clarify = "clarify"  # the question is too vague: ask the user
    unsupported = "unsupported"  # the data cannot answer it


class Period(StrEnum):
    latest_month = "latest_month"  # the latest complete month published ("this month")
    previous_month = "previous_month"  # the month before it ("last month")
    last_3_months = "last_3_months"
    all_months = "all_months"
    custom = "custom"  # start_month / end_month given


class Operator(StrEnum):
    eq = "="
    neq = "!="
    in_ = "in"
    not_in = "not in"


class Filter(BaseModel):
    dimension: str
    operator: Operator = Operator.eq
    values: list[str | int | bool] = Field(min_length=1, max_length=50)


class DateRange(BaseModel):
    period: Period = Period.all_months
    start_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class QueryPlan(BaseModel):
    """What the manager asked, in governed terms. Produced by the LLM, validated by code."""

    intent: Intent
    metrics: list[str] = Field(default_factory=list, max_length=5)
    dimensions: list[str] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    date_range: DateRange = Field(default_factory=DateRange)
    compare_to: Literal["none", "previous_period"] = "none"
    grain: Literal["day", "week", "month", "hour"] | None = None
    order: Literal["desc", "asc", "change_desc", "change_asc"] = "desc"
    limit: int = Field(default=10, ge=1, le=100)
    clarification_question: str | None = None
    unsupported_reason: str | None = None

    @field_validator("metrics", "dimensions")
    @classmethod
    def no_duplicates(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(v.strip() for v in values))


class ReportRequest(QueryPlan):
    """A plan plus what the manager wants to see: a draft chart or dashboard (exam Q8)."""

    chart_recommendation: Literal["line", "bar", "table", "big_number", "pie"] = "line"
    dashboard_title: str = Field(default="Draft report", max_length=120)
    explanation: str = Field(default="", max_length=600)
    extra_charts: list[QueryPlan] = Field(default_factory=list, max_length=3)


class MetricProvenance(BaseModel):
    name: str
    label: str
    definition: str
    sql_expression: str
    unit: str
    filters: str
    is_estimate: bool


class Provenance(BaseModel):
    metrics: list[MetricProvenance]
    source_months: list[str]
    period_resolved: dict[str, str]
    published_run: str
    published_at: str
    valid_trip_rate: float | None
    active_filters: list[Filter]
    rendered_sql: str
    row_count: int
    data_layer: str = "analytics (published layer, read-only role ai_reader)"


class Answer(BaseModel):
    session_id: str
    status: Literal[
        "answered",
        "clarify",
        "rejected",
        "unsupported",
        "empty",
        "model_unavailable",
        "query_failed",
    ]
    question: str
    plan: QueryPlan | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    narrative: str = ""
    narrative_check: Literal["passed", "replaced", "not_needed"] = "not_needed"
    suggested_chart: str | None = None
    suggested_followup: str | None = None
    limitations: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None
    active_filters: list[Filter] = Field(default_factory=list)
    duration_ms: int = 0
