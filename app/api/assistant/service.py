"""The question-answering flow (exam Q9):

question -> guards -> LLM plan (JSON schema) -> validation -> SQL template -> SQLGlot
-> PostgreSQL as ai_reader -> result + provenance -> LLM narrative from the result only
-> number check -> answer, audited at every step.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import psycopg

from assistant import forecast_questions, guards, metrics, retrieval, telemetry
from assistant.catalog import DIMENSIONS, RELATIONS, Catalog, load_catalog
from assistant.config import Settings
from assistant.grounding import ground, named_period, names_a_metric
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
    DateRange,
    Filter,
    Intent,
    MetricProvenance,
    Period,
    Provenance,
    QueryPlan,
    ReportRequest,
)
from assistant.store import Store
from assistant.validator import PlanRejected, resolve_months, validate

ROLE_TEXT = {"current": "this period", "previous": "previous period", "change": "change"}
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def month_name(month: str) -> str:
    """'2025-04' -> 'April 2025'."""
    year, number = month.split("-")[:2]
    return f"{MONTH_NAMES[int(number) - 1]} {year}"


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
    # The last exchanges (question, answer text), for a conversation that follows on.
    history: list[tuple[str, str]] = field(default_factory=list)
    # The scope of the last answer when it came from the forecast ("and for Queens?").
    last_forecast: forecast_questions.ForecastAsk | None = None


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
            settings.llm_output_mode,
            settings.llm_concurrency,
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
        rejected: tuple[QueryPlan, list[str]] | None = None,
    ) -> QueryPlan:
        """The model's plan. `rejected` (a plan and the validator's reasons) asks for one
        corrected plan of the same question."""
        system = planning_prompt(variant or self.settings.prompt_variant, self.catalog().summary())
        retrieved = (
            retrieval.retrieved_context(question, self.catalog()) if self.settings.rag else ""
        )
        message = planning_message(self.context(session), question, retrieved)
        if rejected:
            previous, reasons = rejected
            message += (
                "\n\nYour previous plan for this QUESTION was rejected by the validator:\n- "
                + "\n- ".join(reasons)
                + f"\nRejected plan: {previous.model_dump_json(exclude_defaults=True)}\n"
                "Return a corrected plan for the same QUESTION. Use only names and values of "
                "the vocabulary, and do not add filters the question does not ask for."
            )
        return self.llm.structured(system, message, model_cls)

    def plan_report(self, question: str) -> ReportRequest:
        """A report request: the planning prompt plus the report instructions (exam Q8)."""
        system = planning_prompt(self.settings.prompt_variant, self.catalog().summary())
        system += load_prompt("report")
        retrieved = (
            retrieval.retrieved_context(question, self.catalog()) if self.settings.rag else ""
        )
        return self.llm.structured(
            system,
            planning_message(self.context(Session("r")), question, retrieved),
            ReportRequest,
        )

    def warm_up(self) -> dict[str, int]:
        """Read the planner and narrator system prompts into Ollama's cache, so the first
        real question pays only its own tokens (measured: 75 s cold, 3 to 8 s cached)."""
        timings: dict[str, int] = {}
        with telemetry.step("warm_up_data", timings):
            try:  # the views of the query templates, into PostgreSQL's memory
                views = sorted({spec["from"].split()[0] for spec in RELATIONS.values()})
                print(f"views loaded in memory (blocks): {self.store.prewarm(views)}")
            except Exception as exc:  # noqa: BLE001 - pg_prewarm missing: only slower questions
                print(f"views not prewarmed: {exc}")
        system = planning_prompt(self.settings.prompt_variant, self.catalog().summary())
        with telemetry.step("warm_up_planner", timings):
            self.llm.warm_up(self.llm.planner_system(system, QueryPlan))
        with telemetry.step("warm_up_narrator", timings):
            self.llm.warm_up(load_prompt("narrate"))
        with telemetry.step("warm_up_conversation", timings):
            self.llm.warm_up(load_prompt("converse"))
        return timings

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
            telemetry.start_usage()
            answer = self._ask(question, session_id, variant, {})
            span.set_attribute("assistant.session_id", answer.session_id)
            span.set_attribute("assistant.status", answer.status)
            span.set_attribute("assistant.narrative_check", answer.narrative_check)
        metrics.observe(answer, variant)
        # One log line per answer: Loki keeps the trace id, so a log line opens its trace.
        print(
            f"answer status={answer.status} check={answer.narrative_check} "
            f"seconds={answer.duration_ms / 1000:.1f} session={answer.session_id} "
            f"variant={variant} trace_id={answer.trace_id}",
            flush=True,
        )
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
            session.history = (session.history + [(question, answer.narrative[:600])])[-4:]
            answer.duration_ms = int((time.monotonic() - start) * 1000)
            answer.active_filters = list(session.active_filters)
            answer.step_ms = dict(timings)
            answer.trace_id = telemetry.current_trace_id()
            answer.llm_usage = telemetry.current_usage()
            self.store.audit(
                **base,
                verdict=answer.status,
                reasons=answer.reasons,
                plan=answer.plan.model_dump(mode="json") if answer.plan else None,
                duration_ms=answer.duration_ms,
                step_ms=answer.step_ms,
                trace_id=answer.trace_id,
                llm_usage=answer.llm_usage,
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

        # 2. A question about next month: the published forecast, answered by code.
        with telemetry.step("forecast", timings):
            routed = self.forecast_answer(question, session)
        if routed is not None:
            forecast_answer, audit = routed
            return finish(forecast_answer, **audit)
        session.last_forecast = None

        # 3. Plan with the model (structured output).
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

        # A month the question names is checked by code, whatever the model concluded: a
        # month outside the published coverage gets the coverage as the reason, not a
        # vague "unsupported" (observed: "trips in March 2023" called unsupported).
        cat = self.catalog()
        named = named_period(question)
        if plan.intent == Intent.unsupported and named and named.period == Period.custom:
            try:
                resolve_months(QueryPlan(intent=Intent.lookup, date_range=named), cat.months)
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
        # A conversation, not a data request: a concept, the platform, the assistant itself,
        # general knowledge. A "clarify" plan for a question that names no measure is one
        # too (observed: "do you think your answers should be more written?" was answered
        # with "which measure do you want?").
        if plan.intent == Intent.general or (
            plan.intent == Intent.clarify and not names_a_metric(question)
        ):
            try:
                with telemetry.step("converse", timings):
                    text, removed = self.converse(question, session)
            except ModelUnavailable as exc:
                return finish(
                    Answer(
                        session_id=session.session_id,
                        status="model_unavailable",
                        question=question,
                        reasons=[str(exc)],
                        narrative="The language model is not available right now. The "
                        "dashboards still show every governed measure.",
                    )
                )
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="general",
                    question=question,
                    plan=plan.model_copy(update={"intent": Intent.general}),
                    narrative=text,
                    narrative_check="replaced" if removed else "not_needed",
                    reasons=(
                        [
                            f"{removed} sentence(s) with figures of the taxi data removed: such "
                            "figures come only from governed queries"
                        ]
                        if removed
                        else []
                    ),
                    suggested_followup="How many trips did we have last month?",
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

        # 4. Grounding in the question, validation and policy, with one repair for
        # vocabulary mistakes of the model.
        context_filters = list(session.active_filters) + (
            list(session.last_plan.filters) if session.last_plan else []
        )
        grounded = ground(
            self.merge_follow_up(plan, session), question, cat, context_filters, session.last_plan
        )
        plan, adjusted = grounded.plan, list(grounded.notes)
        repaired: list[str] = []

        def rejected_answer(reasons: list[str], shown: QueryPlan) -> Answer:
            return finish(
                Answer(
                    session_id=session.session_id,
                    status="rejected",
                    question=question,
                    plan=shown,
                    reasons=reasons,
                    narrative="I cannot answer this as asked: " + "; ".join(reasons) + ".",
                )
            )

        try:
            with telemetry.step("validate", timings):
                if grounded.missing:
                    raise PlanRejected(grounded.missing)
                resolved = validate(plan, cat)
                built = build(resolved, cat, self.settings.max_rows)
        except PlanRejected as exc:
            if not exc.repairable:
                return rejected_answer(exc.reasons, plan)
            try:
                with telemetry.step("repair", timings):
                    fixed = self.plan(question, session, variant, rejected=(plan, exc.reasons))
                if fixed.intent in (Intent.clarify, Intent.unsupported):
                    return rejected_answer(exc.reasons, plan)
                regrounded = ground(
                    self.merge_follow_up(fixed, session),
                    question,
                    cat,
                    context_filters,
                    session.last_plan,
                )
                fixed = regrounded.plan
                with telemetry.step("validate_repaired", timings):
                    if regrounded.missing:
                        raise PlanRejected(regrounded.missing)
                    resolved = validate(fixed, cat)
                    built = build(resolved, cat, self.settings.max_rows)
                adjusted += regrounded.notes
            except PlanRejected as again:
                return rejected_answer(
                    exc.reasons + [f"still invalid after one repair: {r}" for r in again.reasons],
                    plan,
                )
            except (ModelUnavailable, MalformedOutput):
                return rejected_answer(exc.reasons, plan)
            except UnsafeSQL as unsafe:
                return rejected_answer([f"SQL guard: {unsafe}"], fixed)
            plan, repaired = fixed, exc.reasons
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

        # 5. Execution as ai_reader.
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

        # 6. Narrative from the result only, then the number check.
        with telemetry.step("narrate", timings) as span:
            narrative, check, rejected = self.narrate(
                question, plan, columns, rows, period, filters
            )
            span.set_attribute("assistant.narrative_check", check)
        # A replaced narrative is kept with the numbers that were not in the result, so the
        # evaluation can show what the guard caught (exam Q10, hallucination risk). A plan
        # repaired after validation says so, with the reasons of the first rejection.
        reasons = [f"plan adjusted: {note}" for note in adjusted]
        reasons += [f"plan repaired after validation: {r}" for r in repaired]
        reasons += [rejected] if rejected else []
        answer = Answer(
            session_id=session.session_id,
            status="answered",
            question=question,
            plan=plan,
            columns=columns,
            rows=rows,
            narrative=narrative,
            narrative_check=check,
            reasons=reasons,
            suggested_chart=self.suggest_chart(plan, built.kind),
            suggested_followup=self.suggest_followup(plan),
            limitations=self.limitations(plan),
            provenance=provenance,
        )
        return finish(answer, rendered_sql=rendered, row_count=len(rows), narrative_check=check)

    # ------------------------------------------------------------------ forecast questions
    def forecast_answer(self, question: str, session: Session) -> tuple[Answer, dict] | None:
        """The answer from the published forecast, or None for the governed path."""
        fq = forecast_questions
        cat = self.catalog()
        if fq.wants_accuracy(question):  # "How accurate was the May forecast?"
            return self.forecast_accuracy(question, session)
        # A question with its own forecast words starts afresh; only a short one without
        # them ("and for Queens?") continues the previous forecast answer.
        fresh = fq.wants_forecast(question, cat)
        follow = (
            not fresh
            and session.last_forecast is not None
            and fq.is_follow_up(question)
            and fq.names_scope(fq.read(question, cat))
        )
        if not follow and not fresh:
            return None

        def refused(status: str, narrative: str, reasons: list[str]) -> tuple[Answer, dict]:
            return (
                Answer(
                    session_id=session.session_id,
                    status=status,
                    question=question,
                    reasons=reasons,
                    narrative=narrative,
                ),
                {},
            )

        measure = None if follow else fq.unforecast_measure(question)
        if measure:
            return refused(
                "unsupported",
                f"Only trips and revenue are forecast, not {measure}. Ask, for example, how "
                "many trips are expected next month in a borough, or the expected revenue.",
                [f"{measure} is not forecast: the forecast covers trips and revenue"],
            )
        ask = (
            fq.follow_up(question, session.last_forecast, cat) if follow else fq.read(question, cat)
        )
        named = named_period(question)
        try:
            run = fq.run_of(self.store, ask.target)
        except fq.NoForecast as exc:
            if named is not None:
                return None  # a month after the published ones: the coverage is explained there
            return refused("unsupported", f"I cannot answer this yet: {exc}.", [str(exc)])
        month = run["forecast_month"]
        if named is not None and (named.start_month, named.end_month) != (month, month):
            reason = (
                f"the published forecast covers {month_name(month)} only; recorded data covers "
                f"{month_name(cat.months[0])} to {month_name(cat.months[-1])}"
            )
            return refused("rejected", f"I cannot answer this as asked: {reason}.", [reason])

        metric = fq.METRIC[ask.target]
        meta = cat.metrics[metric]
        try:
            result = fq.answer(self.store, ask, run, meta["unit"])
        except Exception as exc:  # noqa: BLE001 - any database error is reported, not raised
            return refused(
                "query_failed",
                "The forecast could not be read (time limit or database error).",
                [f"{type(exc).__name__}: {str(exc).splitlines()[0]}"],
            )
        rendered = fq.shown_sql(result.sql, result.params)
        relation, value, _ = fq.SOURCES[ask.target]
        provenance = Provenance(
            metrics=[
                MetricProvenance(
                    name=metric,
                    label=f"{meta['label']} (forecast)",
                    definition=f"Forecast of: {meta['description']}",
                    sql_expression=f"sum({value}) of {relation}",
                    unit=meta["unit"],
                    filters="published forecast of the latest run",
                    is_estimate=True,
                )
            ],
            source_months=list(run["history_months"]),
            period_resolved={"period": month, "compared_with": ""},
            published_run=run["data_run"],
            published_at=run["created_at"],
            valid_trip_rate=None,
            active_filters=result.plan.filters,
            rendered_sql=rendered,
            row_count=len(result.rows),
            data_layer="ml (published forecast, read-only role ai_reader)",
        )
        session.last_forecast = ask
        if not result.rows:
            return (
                Answer(
                    session_id=session.session_id,
                    status="empty",
                    question=question,
                    plan=result.plan,
                    columns=result.columns,
                    provenance=provenance,
                    narrative=f"The forecast has nothing for this selection in "
                    f"{month_name(month)}{fq.scope_text(ask)}.",
                ),
                {"rendered_sql": rendered, "row_count": 0},
            )
        # The figures come from the forecast query; the model only words them, and its text is
        # kept only if every number is in the result and it reads as an estimate.
        with telemetry.step("narrate", {}) as span:
            try:
                text = self.llm.chat(
                    load_prompt("narrate"),
                    fq.model_message(question, ask, result, meta["label"]),
                    max_tokens=320,
                    **self.token_stream(),
                ).strip()
                problem = fq.check_model_text(text, ask, result)
            except ModelUnavailable as exc:
                text, problem = "", f"narrative not written by the model: {exc}"
            check = "replaced" if problem else "passed"
            span.set_attribute("assistant.narrative_check", check)
        reasons = ["forecast: figures from the published forecast, worded by the model"]
        if problem:
            reasons = [
                "forecast: figures from the published forecast, worded by code",
                f"narrative replaced, {problem}. Model text: {text[:400]}",
            ]
        return (
            Answer(
                session_id=session.session_id,
                status="answered",
                question=question,
                plan=result.plan,
                columns=result.columns,
                rows=result.rows,
                narrative=result.narrative if problem else text,
                narrative_check=check,
                reasons=reasons,
                suggested_chart=self.suggest_chart(result.plan, "plain"),
                suggested_followup=(
                    "And by hour?" if ask.by != "pickup_hour" else "And for Queens?"
                ),
                limitations=result.limitations,
                provenance=provenance,
            ),
            {"rendered_sql": rendered, "row_count": len(result.rows), "narrative_check": check},
        )

    def forecast_accuracy(self, question: str, session: Session) -> tuple[Answer, dict]:
        """How a past forecast did, from the forecast-against-actual checks (ml schema)."""
        fq = forecast_questions
        target = "revenue" if fq.REVENUE_WORDS.search(question.lower()) else "trips"
        base = {"session_id": session.session_id, "question": question}
        try:
            columns, rows, narrative, facts = fq.accuracy(self.store, question, target)
        except (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
            columns, rows, narrative, facts = [], [], "", {}
        if not rows:
            return (
                Answer(
                    **base,
                    status="empty",
                    narrative="No forecast has been checked against what happened for that "
                    "month yet: a month is checked once its trips are published.",
                ),
                {},
            )
        month = facts["month"]
        plan = QueryPlan(
            intent=Intent.breakdown,
            metrics=["forecast_error"],
            dimensions=["pickup_borough"],
            date_range=DateRange(period=Period.custom, start_month=month, end_month=month),
        )
        rendered = fq.shown_sql(facts["sql"], {"target": target, "month": month})
        provenance = Provenance(
            metrics=[
                MetricProvenance(
                    name="forecast_error",
                    label="Forecast error per borough and day",
                    definition="Share of the recorded value missed or over-counted (WMAPE) "
                    f"by the published {target} forecast, per borough and day.",
                    sql_expression="sum(|forecast - recorded|) / sum(recorded)",
                    unit="ratio",
                    filters="the live check of the month, else its replay",
                    is_estimate=True,
                )
            ],
            source_months=[month],
            period_resolved={"period": month, "compared_with": ""},
            published_run="ml.forecast_check",
            published_at="",
            valid_trip_rate=None,
            active_filters=[],
            rendered_sql=rendered,
            row_count=len(rows),
            data_layer="ml (forecast against actual, read-only role ai_reader)",
        )
        return (
            Answer(
                **base,
                status="answered",
                plan=plan,
                columns=columns,
                rows=rows,
                narrative=narrative,
                narrative_check="not_needed",
                reasons=["forecast: accuracy from the monthly forecast-against-actual check"],
                suggested_chart="bar",
                suggested_followup="How many trips are expected next month?",
                limitations=[
                    "The error is that of the forecast as it was published, measured once the "
                    "month's trips were recorded.",
                ],
                provenance=provenance,
            ),
            {"rendered_sql": rendered, "row_count": len(rows)},
        )

    # ------------------------------------------------------------------ helpers
    def narrate(
        self, question, plan, columns, rows, period, filters
    ) -> tuple[str, str, str | None]:
        """(narrative, check, rejected): the model's text when every number in it is in the
        result, otherwise the deterministic summary and why the model's text was rejected."""
        metrics = {m: self.catalog().metrics[m] for m in plan.metrics}
        fallback = guards.deterministic_summary(columns, rows, metrics, period, filters)
        # Values already written the way they should be quoted ("382,800.41 USD", "249,175",
        # "90.5 %"): the model copies them instead of converting raw decimals, which is where
        # it erred (observed: 382800.41 written as $38,280.41, 249175 as 2.49 million).
        units = {c: metrics[c]["unit"] for c in columns if c in metrics}
        # Comparison columns carry the unit of their measure, and every header is the
        # governed label: the model copied raw names into its text (observed: "highest
        # total_revenue_current: 202791744.60 USD").
        headers = []
        for c in columns:
            base, _, role = c.rpartition("_")
            if c in metrics:
                headers.append(metrics[c]["label"])
            elif base in metrics and role in ("current", "previous", "change"):
                units[c] = metrics[base]["unit"]
                headers.append(f"{metrics[base]['label']} ({ROLE_TEXT[role]})")
            elif c.endswith("_change_pct") and c[: -len("_change_pct")] in metrics:
                headers.append(f"{metrics[c[: -len('_change_pct')]]['label']} (change %)")
            else:
                headers.append(c.replace("_", " "))
        table = "\n".join(
            [" | ".join(headers)]
            + [
                " | ".join(
                    "" if v is None else guards.format_value(v, units[c]) if c in units else str(v)
                    for c, v in zip(columns, row, strict=True)
                )
                for row in rows[:20]
            ]
        )
        # The definition, not only the label: observed, "tip rate" read as the share of trips
        # with a tip ("20.7 % of card trips had tips") when it is tips divided by the fare.
        message = (
            f"QUESTION: {question}\n"
            "METRICS: "
            + "; ".join(
                f"{m}: {d['label']} ({d['unit']}): {d['description']}" for m, d in metrics.items()
            )
            + f"\nPERIOD: {period}\nFILTERS: {filters or 'none'}\n"
            f"RESULT (columns, then up to 20 rows):\n{table}"
        )
        try:
            # Rules in the system prompt (same every time), data in the message.
            # 2 or 3 sentences fit in 120 tokens; longer output only costs time.
            text = self.llm.chat(
                load_prompt("narrate"), message, max_tokens=320, **self.token_stream()
            ).strip()
        except ModelUnavailable as exc:
            return fallback, "replaced", f"narrative not written by the model: {exc}"
        bad = guards.unsupported_numbers(text, rows[:20])
        if bad or not text:
            numbers = ", ".join(f"{n:g}" for n in bad) or "empty text"
            return (
                fallback,
                "replaced",
                f"narrative replaced, number(s) not in the result: {numbers}. "
                f"Model text: {text[:400]}",
            )
        # True numbers can still support a false comparison ("X had the lowest ...").
        wrong = guards.wrong_rankings(text, columns, rows, plan.metrics[0])
        if wrong:
            return (
                fallback,
                "replaced",
                f"narrative replaced, ranking contradicted by the result: {'; '.join(wrong)}. "
                f"Model text: {text[:400]}",
            )
        # True numbers can also be given to the wrong month of a comparison.
        swapped = guards.swapped_months(text, columns, rows[:20], period)
        if swapped:
            return (
                fallback,
                "replaced",
                f"narrative replaced, months swapped: {'; '.join(swapped[:3])}. "
                f"Model text: {text[:400]}",
            )
        # ... or written with the wrong unit ("37.69 trips" for a 37.69 % change).
        mislabelled = guards.wrong_units(text, columns, rows[:20], units)
        if mislabelled:
            return (
                fallback,
                "replaced",
                f"narrative replaced, wrong unit: {'; '.join(mislabelled[:3])}. "
                f"Model text: {text[:400]}",
            )
        # ... or a true rate given the wrong meaning (a share of trips for tips / fare).
        misread = guards.misread_rates(text, plan.metrics)
        if misread:
            return (
                fallback,
                "replaced",
                f"narrative replaced, definition misread: {'; '.join(misread)}. "
                f"Model text: {text[:400]}",
            )
        return text, "passed", None

    @staticmethod
    def token_stream() -> dict:
        """When someone listens (streaming endpoint), the model's text is passed on as it is
        written; otherwise the call is a plain one (and test doubles need no streaming)."""
        if not telemetry.streaming():
            return {}
        return {"on_token": lambda piece: telemetry.emit({"type": "token", "text": piece})}

    def platform_facts(self) -> str:
        """What the assistant knows about the platform, for conversational answers."""
        cat = self.catalog()
        months = f"{cat.months[0]} to {cat.months[-1]}" if cat.months else "none yet"
        measures = "\n".join(
            f"- {m['label']} ({m['unit']}): {m['description']}" for m in cat.metrics.values()
        )
        dimensions = ", ".join(d.replace("_", " ") for d in DIMENSIONS)
        return (
            "PLATFORM FACTS\n"
            "- Data: NYC TLC Yellow Taxi trip records, monthly files, published months "
            f"{months} (publication {cat.published_run}). One row per completed trip.\n"
            "- Pipeline: bronze (raw, as received) -> silver (typed, quality flags, nothing "
            "deleted) -> gold (star schema and aggregates) -> analytics (published only after "
            "a quality gate). Orchestrated by Airflow with dbt; PostgreSQL; dashboards in "
            "Superset.\n"
            f"- You: a local language model ({self.settings.model}) served by Ollama, on "
            "the platform's own machine; questions never leave it.\n"
            "- How a data answer is produced: you write a JSON plan with governed measures; "
            "code validates it against the catalogue and the question; an approved SQL "
            "template runs read-only on the published layer; you explain the result; code "
            "checks every number of the text against the result and replaces the text if "
            "one is not there. Every answer is logged with its trace.\n"
            f"- Breakdowns available: {dimensions}.\n"
            "- Forecast: next month's trips and revenue per pickup zone, day and hour, "
            "published by a monthly job tracked in MLflow. A seasonal baseline (same weekday "
            "and hour over the last four weeks), an adjusted baseline (recent trend and "
            "last year's seasonality), and a LightGBM model compete on the three "
            "previous months; the winner is used. Questions such as 'How many trips are "
            "expected in Manhattan next month?' are answered from it by code, labelled as "
            "estimates. The Forecast page shows its accuracy; the Shift planner page compares "
            "zones over a shift window.\n"
            "- Not in the data: driver earnings, wait times, cancellations, rider identity, "
            "profit, weather, Uber/Lyft/Green taxis.\n"
            f"- Governed measures:\n{measures}"
        )

    def converse(self, question: str, session: Session) -> tuple[str, int]:
        """A conversational answer: general knowledge and the platform, no data figures."""
        history = "\n".join(
            f"Earlier question: {q}\nYour answer: {a}" for q, a in session.history[-3:]
        )
        message = (
            f"{self.platform_facts()}\n\n"
            + (f"CONVERSATION SO FAR\n{history}\n\n" if history else "")
            + f"QUESTION: {question}"
        )
        text = self.llm.chat(
            load_prompt("converse"), message, max_tokens=500, temperature=0.3, **self.token_stream()
        ).strip()
        text, removed = guards.scrub_data_figures(text)
        if removed:
            text += (
                "\n\n*Figures about the taxi data come only from governed queries: ask me for "
                "the figure and I will compute it from the published data.*"
            )
        return text or "Could you tell me a bit more about what you would like to know?", removed

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
        """Months in words ("April 2025", "March 2025 to April 2025"), as the narrative and
        the factual summary quote them."""

        def span(months: list[str]) -> str:
            names = [month_name(m) for m in months]
            return names[0] if len(names) == 1 else f"{names[0]} to {names[-1]}"

        text = span(resolved.months)
        if resolved.comparison_months:
            text += " compared with " + span(resolved.comparison_months)
        return text

    @staticmethod
    def filters_text(filters: list[Filter]) -> str:
        if not filters:
            return ""

        def one(f: Filter) -> str:
            negated = f.operator.value in ("!=", "not in")
            return (
                f"{f.dimension.replace('_', ' ')}: {'not ' if negated else ''}"
                f"{', '.join(map(str, f.values))}"
            )

        return " (" + "; ".join(one(f) for f in filters) + ")"

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
            return f"Compare with the previous month by {plan.dimensions[0].replace('_', ' ')}."
        return "Break this down by pickup borough."
