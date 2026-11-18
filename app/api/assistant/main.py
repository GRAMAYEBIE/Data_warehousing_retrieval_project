"""FastAPI application of the AI assistant.

Every endpoint except /health requires `Authorization: Bearer <API_TOKEN>`.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from assistant.config import Settings
from assistant.service import Assistant

app = FastAPI(
    title="NYC Taxi Insight Hub assistant",
    version="1.0.0",
    description="Governed natural-language analytics: the language model plans and explains; "
    "approved query templates compute from the published layer.",
)


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
def health() -> dict:
    assistant = get_assistant()
    try:
        catalog = assistant.catalog()
        database = "ok"
        months = catalog.months
    except Exception as exc:  # noqa: BLE001
        database, months = f"error: {type(exc).__name__}", []
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "model": assistant.settings.model,
        "model_available": assistant.llm.available(),
        "complete_months": months,
    }


@app.get("/catalog", dependencies=[Depends(authorised)])
def catalog() -> dict:
    cat = get_assistant().catalog(refresh=True)
    from assistant.catalog import DIMENSIONS

    return {
        "metrics": cat.metrics,
        "dimensions": {
            d.name: {"label": d.label, "members": cat.members.get(d.name, [])}
            for d in DIMENSIONS.values()
        },
        "complete_months": cat.months,
        "published_run": cat.published_run,
        "published_at": cat.published_at,
    }


@app.post("/sessions", dependencies=[Depends(authorised)])
def new_session() -> dict:
    return {"session_id": get_assistant().new_session().session_id}


@app.post("/sessions/{session_id}/ask", dependencies=[Depends(authorised)])
def ask(session_id: str, body: AskBody):
    return get_assistant().ask(body.question, session_id, body.prompt_variant)


@app.post("/sessions/{session_id}/reset", dependencies=[Depends(authorised)])
def reset(session_id: str) -> dict:
    session = get_assistant().reset(session_id)
    return {"session_id": session.session_id, "active_filters": [], "status": "new analysis"}


class ReportBody(BaseModel):
    request: str = Field(min_length=10, max_length=600)


class ConfirmBody(BaseModel):
    confirm: bool = False
    replace_existing: bool = False


@lru_cache
def get_builder():
    from assistant.builder import ReportBuilder

    return ReportBuilder(get_assistant())


def draft_view(draft) -> dict:
    url = f"/superset/dashboard/{draft.dashboard_id}/"
    return {
        "report_id": draft.report_id,
        "status": draft.status,
        "dashboard_title": draft.title,
        "dashboard_id": draft.dashboard_id,
        "dashboard_url": url,
        "chart_ids": draft.chart_ids,
        "specification": draft.spec,
        "preview": draft.preview,
        "next_step": (
            "Review the draft, then POST /reports/{id}/confirm with confirm=true to publish."
            if draft.status == "draft"
            else "Published."
        ),
    }


@app.post("/reports", dependencies=[Depends(authorised)])
def create_report(body: ReportBody) -> dict:
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
def get_report(report_id: str) -> dict:
    draft = get_builder().drafts.get(report_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="unknown report")
    return draft_view(draft)


@app.post("/reports/{report_id}/confirm", dependencies=[Depends(authorised)])
def confirm_report(report_id: str, body: ConfirmBody) -> dict:
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
def session_state(session_id: str) -> dict:
    s = get_assistant().session(session_id)
    return {
        "session_id": s.session_id,
        "turns": s.turns,
        "active_filters": [f.model_dump(mode="json") for f in s.active_filters],
        "last_plan": s.last_plan.model_dump(mode="json") if s.last_plan else None,
    }
