"""The question-answering flow (exam Q9):

question -> guards -> LLM plan (JSON schema) -> validation -> SQL template -> SQLGlot
-> PostgreSQL as ai_reader -> result + provenance -> LLM narrative from the result only
-> number check -> answer, audited at every step.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from assistant import guards, telemetry
from assistant.catalog import Catalog, load_catalog
from assistant.config import Settings
from assistant.llm import (
    MalformedOutput,
    ModelUnavailable,
    Ollama,
    load_prompt,
    planning_message,
    planning_prompt,
)
from assistant.resolver import UnsafeSQL, build, pivot_comparison, render
from assistant.schemas import (
    Answer,
    Filter,
    Intent,
    MetricProvenance,
    Provenance,
    QueryPlan,
    ReportRequest,
)
from assistant.store import Store
from assistant.validator import PlanRejected, validate

LIMITATIONS = [
    "Trip volume is a proxy for demand: unserved demand is not visible.",
    "Data is reported by vendors; TLC does not guarantee its accuracy.",
]


@dataclass
class Session:
    session_id: str
    active_filters: list[Filter] = field(default_factory=list)
    last_plan: QueryPlan | None = None
    turns: int = 0


class Assistant:
    def __init__(
        self, settings: Settings, llm: Ollama | None = None, store: Store | None = None
    ) -> None:
        self.settings = settings
        self.llm = llm or Ollama(
            settings.ollama_url,
            settings.model,
            settings.llm_timeout_s,
            settings.llm_threads,
            settings.llm_keep_alive,
        )
        self.store = store or Store(settings)
        self.sessions: dict[str, Session] = {}
        self._catalog: Catalog | None = None

    # ------------------------------------------------------------------ catalogue, sessions
    def catalog(self, refresh: bool = False) -> Catalog:
        if self._catalog is None or refresh:
            with self.store.reader() as conn:
                self._catalog = load_catalog(conn)
        return self._catalog

    def new_session(self) -> Session:
        session = Session(session_id=uuid.uuid4().hex[:12])
        self.sessions[session.session_id] = session
        return session

    def session(self, session_id: str) -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(session_id=session_id)
        return self.sessions[session_id]

    def reset(self, session_id: str) -> Session:
        self.sessions[session_id] = Session(session_id=session_id)
        return self.sessions[session_id]

    # ------------------------------------------------------------------ planning
    def context(self, session: Session) -> str:
        cat = self.catalog()
        lines = [
            f"Latest complete month: {cat.months[-1]}." if cat.months else "No data yet.",
        ]
        if session.last_plan:
            lines.append(
                "PREVIOUS PLAN of this conversation (a follow-up question may "
                "change only part of it): "
                + session.last_plan.model_dump_json(exclude_defaults=True)
            )
        if session.active_filters:
            lines.append(
                "ACTIVE FILTERS: "
                + "; ".join(
                    f"{f.dimension} {f.operator.value} {', '.join(map(str, f.values))}"
                    for f in session.active_filters
                )
            )
        return "\n".join(lines)

    def plan(
        self,
        question: str,
        session: Session,
        variant: str | None = None,
        model_cls: type[QueryPlan] = QueryPlan,
    ) -> QueryPlan:
        system = planning_prompt(variant or self.settings.prompt_variant, self.catalog().summary())
        return self.llm.structured(
            system, planning_message(self.context(session), question), model_cls
        )

    def plan_report(self, question: str) -> ReportRequest:
        """A report request: the planning prompt plus the report instructions (exam Q8)."""
        system = planning_prompt(self.settings.prompt_variant, self.catalog().summary())
        system += load_prompt("report")
        return self.llm.structured(
            system, planning_message(self.context(Session("r")), question), ReportRequest
        )

    @staticmethod
    def merge_follow_up(plan: QueryPlan, session: Session) -> QueryPlan:
        """A follow-up keeps what it does not change: metrics and active filters."""
        if plan.intent in (Intent.clarify, Intent.unsupported):
            return plan
        if not plan.metrics and session.last_plan:
            plan.metrics = list(session.last_plan.metrics)
        new_dims = {f.dimension for f in plan.filters}
        kept = [f for f in session.active_filters if f.dimension not in new_dims]
        plan.filters = kept + plan.filters
        return plan

    # ------------------------------------------------------------------ answering
    def ask(
        self, question: str, session_id: str | None = None, variant: str | None = None
    ) -> Answer:
        """One question = one trace (root span), one child span per step."""
        variant = variant or self.settings.prompt_variant
        with telemetry.tracer.start_as_current_span(
            "assistant.ask",
            attributes={
                "assistant.prompt_variant": variant,
                "assistant.model": self.settings.model,
            },
        ) as span:
            answer = self._ask(question, session_id, variant, {})
            span.set_attribute("assistant.session_id", answer.session_id)
            span.set_attribute("assistant.status", answer.status)
            span.set_attribute("assistant.narrative_check", answer.narrative_check)
            return answer

    def _ask(self, question: str, session_id: str | None, variant: str, timings: dict) -> Answer:
        start = time.monotonic()
        session = self.session(session_id) if session_id else self.new_session()
        session.turns += 1
        base = {
            "session_id": session.session_id,
            "question": question,
            "prompt_variant": variant,
            "model": self.settings.model,
        }

        def finish(answer: Answer, **audit) -> Answer:
            answer.duration_ms = int((time.monotonic() - start) * 1000)
            answer.active_filters = list(session.active_filters)
            answer.step_ms = dict(timings)
            answer.trace_id = telemetry.current_trace_id()
            self.store.audit(
                **base,
                verdict=answer.status,
                reasons=answer.reasons,
                plan=answer.plan.model_dump(mode="json") if answer.plan else None,
                duration_ms=answer.duration_ms,
                step_ms=answer.step_ms,
                trace_id=answer.trace_id,
                **audit,
            )
            return answer

        # 1. Deterministic guards, before the model.
        with telemetry.step("guards", timings):
            injected = guards.injection_detected(question)
            reason = guards.unsupported_reason(question)
        if injected:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="rejected",
                    question=question,
                    reasons=[
                        "the question contains instructions to change data or rules; "
                        "the assistant only reads governed metrics"
                    ],
                    narrative="I can only answer analytical questions with governed metrics. "
                    "I cannot run commands or change data.",
                )
            )
        if reason:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="unsupported",
                    question=question,
                    reasons=[reason],
                    limitations=[reason],
                    narrative=(
                        "This question cannot be answered with the published data: "
                        f"{reason}. Ask about trips, revenue, fares, tips, distance, "
                        "duration, airports or data quality."
                    ),
                )
            )

        # 2. Plan with the model (structured output).
        try:
            with telemetry.step("plan", timings):
                plan = self.plan(question, session, variant)
        except ModelUnavailable as exc:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="model_unavailable",
                    question=question,
                    reasons=[str(exc)],
                    narrative="The language model is not available right now. The dashboards "
                    "and governed metrics are still available in Superset.",
                )
            )
        except MalformedOutput as exc:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="rejected",
                    question=question,
                    reasons=[f"malformed plan: {exc}"],
                    narrative="I could not turn this question into a valid plan. "
                    "Please rephrase it with a metric, for example trips or revenue.",
                )
            )

        if plan.intent == Intent.unsupported:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="unsupported",
                    question=question,
                    plan=plan,
                    reasons=[plan.unsupported_reason or "outside the data"],
                    narrative=plan.unsupported_reason or "The data cannot answer this question.",
                )
            )
        if plan.intent == Intent.clarify:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="clarify",
                    question=question,
                    plan=plan,
                    narrative=plan.clarification_question
                    or "Which measure do you mean: trips, total revenue or average fare?",
                )
            )

        # 3. Validation and policy.
        plan = self.merge_follow_up(plan, session)
        try:
            with telemetry.step("validate", timings):
                resolved = validate(plan, self.catalog())
                built = build(resolved, self.catalog(), self.settings.max_rows)
        except PlanRejected as exc:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="rejected",
                    question=question,
                    plan=plan,
                    reasons=exc.reasons,
                    narrative="I cannot answer this as asked: " + "; ".join(exc.reasons) + ".",
                )
            )
        except UnsafeSQL as exc:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="rejected",
                    question=question,
                    plan=plan,
                    reasons=[f"SQL guard: {exc}"],
                    narrative="The generated query did not pass the safety checks.",
                )
            )

        # 4. Execution as ai_reader.
        rendered = render(built.sql, built.params)
        try:
            with telemetry.step("execute", timings, **{"assistant.template": built.kind}):
                columns, rows, _ = self.store.query(built.sql, built.params)
        except Exception as exc:  # noqa: BLE001 - any database error is reported, not raised
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="query_failed",
                    question=question,
                    plan=plan,
                    reasons=[f"{type(exc).__name__}: {str(exc).splitlines()[0]}"],
                    narrative="The query failed (time limit or database error). Try a narrower "
                    "question, for example one month or one borough.",
                ),
                rendered_sql=rendered,
            )
        rows = [list(r) for r in rows]
        if built.kind == "compare":
            columns, rows = pivot_comparison(
                columns, rows, plan.dimensions, plan.metrics, plan.order, plan.limit
            )

        session.last_plan = plan
        session.active_filters = resolved.filters
        with telemetry.step("provenance", timings):
            provenance = self.provenance(resolved, rendered, len(rows))
        period = self.period_text(resolved)
        filters = self.filters_text(resolved.filters)

        if not rows:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="empty",
                    question=question,
                    plan=plan,
                    columns=columns,
                    provenance=provenance,
                    narrative=f"No trips match this question for {period}{filters}. The filters "
                    "may be too narrow, or the activity did not happen in that period.",
                    suggested_followup="Try removing a filter or choosing all months.",
                ),
                rendered_sql=rendered,
                row_count=0,
            )

        # 5. Narrative from the result only, then the number check.
        with telemetry.step("narrate", timings) as span:
            narrative, check = self.narrate(question, plan, columns, rows, period, filters)
            span.set_attribute("assistant.narrative_check", check)
        answer = Answer(
            session_id=session.session_id,
            status="answered",
            question=question,
            plan=plan,
            columns=columns,
            rows=rows,
            narrative=narrative,
            narrative_check=check,
            suggested_chart=self.suggest_chart(plan, built.kind),
            suggested_followup=self.suggest_followup(plan),
            limitations=self.limitations(plan),
            provenance=provenance,
        )
        return finish(answer, rendered_sql=rendered, row_count=len(rows), narrative_check=check)

    # ------------------------------------------------------------------ helpers
    def narrate(self, question, plan, columns, rows, period, filters) -> tuple[str, str]:
        metrics = {m: self.catalog().metrics[m] for m in plan.metrics}
        fallback = guards.deterministic_summary(columns, rows, metrics, period, filters)
        table = "\n".join(
            [" | ".join(columns)]
            + [" | ".join("" if v is None else str(v) for v in row) for row in rows[:20]]
        )
        message = (
            f"QUESTION: {question}\n"
            "METRICS: "
            + "; ".join(f"{m}: {d['label']} ({d['unit']})" for m, d in metrics.items())
            + f"\nPERIOD: {period}\nFILTERS: {filters or 'none'}\n"
            f"RESULT (columns, then up to 20 rows):\n{table}"
        )
        try:
            # Rules in the system prompt (same every time), data in the message.
            text = self.llm.chat(load_prompt("narrate"), message, max_tokens=220).strip()
        except ModelUnavailable:
            return fallback, "replaced"
        bad = guards.unsupported_numbers(text, rows[:20])
        if bad or not text:
            return fallback, "replaced"
        return text, "passed"

    def provenance(self, resolved, rendered: str, row_count: int) -> Provenance:
        cat = self.catalog()
        months = resolved.months + resolved.comparison_months
        return Provenance(
            metrics=[
                MetricProvenance(
                    name=m,
                    label=cat.metrics[m]["label"],
                    definition=cat.metrics[m]["description"],
                    sql_expression=cat.metrics[m]["sql_expression"],
                    unit=cat.metrics[m]["unit"],
                    filters=cat.metrics[m]["filters"],
                    is_estimate=cat.metrics[m]["is_estimate"],
                )
                for m in resolved.plan.metrics
            ],
            source_months=sorted(months),
            period_resolved={
                "period": ", ".join(resolved.months),
                "compared_with": ", ".join(resolved.comparison_months),
            },
            published_run=cat.published_run,
            published_at=cat.published_at,
            valid_trip_rate=self.store.valid_trip_rate(months),
            active_filters=resolved.filters,
            rendered_sql=rendered,
            row_count=row_count,
        )

    @staticmethod
    def period_text(resolved) -> str:
        text = (
            resolved.months[0]
            if len(resolved.months) == 1
            else f"{resolved.months[0]} to {resolved.months[-1]}"
        )
        if resolved.comparison_months:
            text += " compared with " + (
                resolved.comparison_months[0]
                if len(resolved.comparison_months) == 1
                else f"{resolved.comparison_months[0]} to {resolved.comparison_months[-1]}"
            )
        return text

    @staticmethod
    def filters_text(filters: list[Filter]) -> str:
        if not filters:
            return ""
        return (
            " ("
            + "; ".join(
                f"{f.dimension} {f.operator.value} {', '.join(map(str, f.values))}" for f in filters
            )
            + ")"
        )

    def limitations(self, plan: QueryPlan) -> list[str]:
        notes = list(LIMITATIONS)
        cat = self.catalog().metrics
        if any(cat[m]["is_estimate"] for m in plan.metrics):
            notes.append("CO2 is an estimate (distance x 0.400 kg per mile), not a measurement.")
        if any(m in ("avg_tip", "tip_rate") for m in plan.metrics):
            notes.append("Tips are recorded for card payments only.")
        return notes

    @staticmethod
    def suggest_chart(plan: QueryPlan, kind: str) -> str:
        if plan.intent == Intent.trend:
            return "line"
        if kind == "compare" or plan.intent in (Intent.rank, Intent.breakdown):
            return "bar"
        return "big_number"

    @staticmethod
    def suggest_followup(plan: QueryPlan) -> str:
        if plan.intent == Intent.compare:
            return "Ask for the weekly trend of the zones that changed most."
        if plan.dimensions:
            return f"Compare with the previous month by {plan.dimensions[0]}."
        return "Break this down by pickup borough."
