"""Structured contracts between the LLM, the validator, the resolver and the user.

The LLM never returns SQL or numbers: it returns a QueryPlan (or a ReportRequest), which
is validated against the governed catalogue before anything touches the database.
Relative periods are words ("last_month"), resolved to dates by code, not by the model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contract(BaseModel):
    """Base of the models the API returns: in responses, a field with a default is always
    present, so the OpenAPI contract marks it required (the generated TypeScript types then
    need no undefined checks for fields the API always sends)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Intent(StrEnum):
    trend = "trend"  # a metric over time
    compare = "compare"  # a period versus another period
    rank = "rank"  # top or bottom N members of a dimension
    breakdown = "breakdown"  # a metric split by a dimension
    lookup = "lookup"  # one value
    clarify = "clarify"  # the question is too vague: ask the user
    unsupported = "unsupported"  # the data cannot answer it
    # Not a request for figures from the taxi data: a concept, the project, the assistant
    # itself, general knowledge. Answered in conversation, never with figures of the data.
    general = "general"


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


class Filter(Contract):
    dimension: str
    operator: Operator = Operator.eq
    values: list[str | int | bool] = Field(min_length=1, max_length=50)


class DateRange(Contract):
    period: Period = Period.all_months
    start_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class QueryPlan(Contract):
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


class MetricProvenance(Contract):
    name: str
    label: str
    definition: str
    sql_expression: str
    unit: str
    filters: str
    is_estimate: bool


class Provenance(Contract):
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


class Answer(Contract):
    session_id: str
    status: Literal[
        "answered",
        "clarify",
        "rejected",
        "unsupported",
        "empty",
        "model_unavailable",
        "query_failed",
        "general",  # a conversational answer, not computed from the data
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
    step_ms: dict[str, int] = Field(default_factory=dict)  # guards, plan, validate, ...
    trace_id: str | None = None  # OpenTelemetry trace of this answer
    # Per step: model calls, tokens read now (cached ones are not counted), tokens written,
    # and the time of each, e.g. {"plan": {"prompt_tokens": 41, "output_tokens": 23, ...}}.
    llm_usage: dict[str, dict[str, int]] = Field(default_factory=dict)
