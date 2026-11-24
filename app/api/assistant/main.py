"""FastAPI application of the AI assistant.

Every endpoint except /health requires `Authorization: Bearer <API_TOKEN>`.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from assistant import telemetry
from assistant.api_models import (
    CatalogView,
    DimensionInfo,
    Health,
    OverviewView,
    Rejection,
    ReportPreview,
    ReportView,
    SessionCreated,
    SessionReset,
    SessionState,
    WarmUp,
)
from assistant.config import Settings
from assistant.schemas import Answer
from assistant.service import Assistant

WARM_UP = {"state": "not started", "step_ms": {}}


def warm_up() -> None:
    """Background: the API answers /health at once while the prompts are being cached."""
    WARM_UP["state"] = "running"
    try:
        WARM_UP["step_ms"] = get_assistant().warm_up()
        WARM_UP["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - a failed warm-up only means a slower first answer
        WARM_UP["state"] = f"failed: {type(exc).__name__}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("ASSISTANT_WARM_UP", "true").lower() == "true":
        threading.Thread(target=warm_up, name="prompt-cache-warm-up", daemon=True).start()
    yield


app = FastAPI(
    title="NYC Taxi Insight Hub assistant",
    version="1.0.0",
    description="Governed natural-language analytics: the language model plans and explains; "
    "approved query templates compute from the published layer.",
    lifespan=lifespan,
)
telemetry.setup(app)


@lru_cache
def get_assistant() -> Assistant:
    return Assistant(Settings.from_env())


def authorised(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {get_assistant().settings.api_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="missing or invalid API token")


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    prompt_variant: str | None = Field(
        default=None, pattern=r"^(v1_minimal|v2_rules|v3_structured_examples)$"
    )


@app.get("/health")
def health() -> Health:
    assistant = get_assistant()
    try:
        catalog = assistant.catalog()
        database = "ok"
        months = catalog.months
    except Exception as exc:  # noqa: BLE001
        database, months = f"error: {type(exc).__name__}", []
    return Health(
        status="ok" if database == "ok" else "degraded",
        database=database,
        model=assistant.settings.model,
        model_available=assistant.llm.available(),
        output_mode=assistant.llm.output_mode,
        retrieval=assistant.settings.rag,
        prompt_cache_warm_up=WarmUp(**WARM_UP),
        complete_months=months,
    )


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Counts and durations for Prometheus; no question text and no data value."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/catalog", dependencies=[Depends(authorised)])
def catalog() -> CatalogView:
    cat = get_assistant().catalog(refresh=True)
    from assistant.catalog import DIMENSIONS

    return CatalogView(
        metrics=cat.metrics,
        dimensions={
            d.name: DimensionInfo(label=d.label, members=cat.members.get(d.name, []))
            for d in DIMENSIONS.values()
        },
        complete_months=cat.months,
        published_run=cat.published_run,
        published_at=cat.published_at,
    )


@app.get("/overview", dependencies=[Depends(authorised)])
def overview() -> OverviewView:
    """The key figures of the latest month, computed like an answer but without the model."""
    from assistant import overview as page

    try:
        return OverviewView.model_validate(page.compute(get_assistant()))
    except Exception as exc:  # noqa: BLE001 - the page reports the failure, the API stays up
        raise HTTPException(503, f"overview unavailable: {type(exc).__name__}") from exc


@app.post("/sessions", dependencies=[Depends(authorised)])
def new_session() -> SessionCreated:
    return SessionCreated(session_id=get_assistant().new_session().session_id)


@app.post("/sessions/{session_id}/ask", dependencies=[Depends(authorised)])
def ask(session_id: str, body: AskBody) -> Answer:
    return get_assistant().ask(body.question, session_id, body.prompt_variant)


@app.post(
    "/sessions/{session_id}/ask/stream",
    dependencies=[Depends(authorised)],
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {}}}},
)
def ask_stream(session_id: str, body: AskBody) -> StreamingResponse:
    """The same answer as /ask, with its progress as it happens, one JSON object per line:
    {"type": "step", "step": "plan", "state": "start" | "done", "ms": ...} for each step,
    {"type": "token", "text": "..."} as the model writes (the text is checked only at the
    end: it may be replaced), then {"type": "answer", "answer": {...}} (the checked
    answer, as /ask returns it) or {"type": "error", "message": "..."}."""
    assistant = get_assistant()
    events: queue.Queue = queue.Queue()
    done = object()

    def work() -> None:
        token = telemetry.set_emitter(events.put)
        try:
            answer = assistant.ask(body.question, session_id, body.prompt_variant)
            events.put({"type": "answer", "answer": answer.model_dump(mode="json")})
        except HTTPException as exc:
            events.put({"type": "error", "message": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - reported to the client, never a broken stream
            events.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            telemetry.reset_emitter(token)
            events.put(done)

    threading.Thread(target=work, daemon=True).start()

    def lines():
        while (event := events.get()) is not done:
            yield json.dumps(event, default=str) + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/sessions/{session_id}/reset", dependencies=[Depends(authorised)])
def reset(session_id: str) -> SessionReset:
    session = get_assistant().reset(session_id)
    return SessionReset(session_id=session.session_id, active_filters=[], status="new analysis")


class ReportBody(BaseModel):
    request: str = Field(min_length=10, max_length=600)


class ConfirmBody(BaseModel):
    confirm: bool = False
    replace_existing: bool = False


@lru_cache
def get_builder():
    from assistant.builder import ReportBuilder

    return ReportBuilder(get_assistant())


def draft_view(draft) -> ReportView:
    return ReportView(
        report_id=draft.report_id,
        status=draft.status,
        dashboard_title=draft.title,
        dashboard_id=draft.dashboard_id,
        dashboard_url=f"/superset/dashboard/{draft.dashboard_id}/",
        chart_ids=draft.chart_ids,
        specification=draft.spec,
        preview=[ReportPreview(**p) for p in draft.preview],
        next_step=(
            "Review the draft, then POST /reports/{id}/confirm with confirm=true to publish."
            if draft.status == "draft"
            else "Published."
        ),
    )


@app.post(
    "/reports",
    dependencies=[Depends(authorised)],
    responses={422: {"model": Rejection, "description": "Request refused, with the reasons"}},
)
def create_report(body: ReportBody) -> ReportView:
    """Plan a report, validate every chart, run the previews and create a DRAFT dashboard."""
    from assistant import guards
    from assistant.builder import BuilderError
    from assistant.llm import MalformedOutput, ModelUnavailable
    from assistant.validator import PlanRejected

    assistant = get_assistant()
    if guards.injection_detected(body.request) or guards.unsupported_reason(body.request):
        reason = guards.unsupported_reason(body.request) or "instructions to change data or rules"
        assistant.store.audit(
            session_id="report", question=body.request, verdict="rejected", reasons=[reason]
        )
        raise HTTPException(status_code=422, detail={"status": "rejected", "reasons": [reason]})
    try:
        request = assistant.plan_report(body.request)
        draft = get_builder().draft(request)
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (MalformedOutput, PlanRejected) as exc:
        reasons = getattr(exc, "reasons", [str(exc)])
        assistant.store.audit(
            session_id="report", question=body.request, verdict="rejected", reasons=reasons
        )
        raise HTTPException(
            status_code=422, detail={"status": "rejected", "reasons": reasons}
        ) from exc
    except BuilderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    assistant.store.audit(
        session_id="report",
        question=body.request,
        verdict="draft_created",
        plan=request.model_dump(mode="json"),
        rendered_sql="\n;\n".join(p["sql"] for p in draft.preview),
        row_count=sum(p["row_count"] for p in draft.preview),
    )
    return draft_view(draft)


@app.get("/reports/{report_id}", dependencies=[Depends(authorised)])
def get_report(report_id: str) -> ReportView:
    draft = get_builder().drafts.get(report_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="unknown report")
    return draft_view(draft)


@app.post("/reports/{report_id}/confirm", dependencies=[Depends(authorised)])
def confirm_report(report_id: str, body: ConfirmBody) -> ReportView:
    """Publication needs confirm=true; replacing an existing dashboard needs replace_existing."""
    from assistant.builder import BuilderError

    try:
        draft = get_builder().confirm(report_id, body.confirm, body.replace_existing)
    except BuilderError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    get_assistant().store.audit(
        session_id="report", question=f"confirm {report_id}", verdict="draft_published"
    )
    return draft_view(draft)


@app.get("/sessions/{session_id}", dependencies=[Depends(authorised)])
def session_state(session_id: str) -> SessionState:
    s = get_assistant().session(session_id)
    return SessionState(
        session_id=s.session_id,
        turns=s.turns,
        active_filters=list(s.active_filters),
        last_plan=s.last_plan,
    )
