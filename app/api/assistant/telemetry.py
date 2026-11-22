"""OpenTelemetry tracing of the assistant.

Every question is one trace: a root span `assistant.ask` and one child span per step
(guards, plan, validate, execute, narrate), plus the spans of the instrumented libraries
(FastAPI request, HTTP calls to Ollama and Superset, PostgreSQL queries). The trace id
and the duration of each step are also returned in the answer and written to
ops.ai_audit_log, so an audit row leads to its trace and back.

Spans are exported only when OTEL_EXPORTER_OTLP_ENDPOINT is set (the observability
profile sends them to Tempo); otherwise they are created, not sent.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

tracer = trace.get_tracer("assistant")
_configured = False
# Model usage of the current answer, per step: {"plan": {"prompt_tokens": ..., ...}}.
_usage: ContextVar[dict | None] = ContextVar("llm_usage", default=None)
_step: ContextVar[str] = ContextVar("assistant_step", default="other")
# Live progress of the answer being computed (the streaming endpoint): step starts and
# ends, and the text as the model writes it. None: nobody listens.
_emitter: ContextVar[Callable[[dict], None] | None] = ContextVar("assistant_emitter", default=None)


def set_emitter(emit: Callable[[dict], None] | None):
    """Send the progress events of this context to `emit`; returns a token for reset."""
    return _emitter.set(emit)


def reset_emitter(token) -> None:
    _emitter.reset(token)


def emit(event: dict) -> None:
    listener = _emitter.get()
    if listener is not None:
        listener(event)


def streaming() -> bool:
    return _emitter.get() is not None


def setup(app=None) -> None:
    """Install the tracer provider and instrument FastAPI, httpx and psycopg (once)."""
    global _configured
    if _configured:
        return
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", "nyc-taxi-assistant")}
        )
    )
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

    HTTPXClientInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health,metrics")
    _configured = True


@contextmanager
def step(name: str, timings: dict[str, int], **attributes) -> Iterator[trace.Span]:
    """One step of the answer: a span, and its duration in milliseconds in `timings`."""
    start = time.monotonic()
    token = _step.set(name)
    emit({"type": "step", "step": name, "state": "start"})
    with tracer.start_as_current_span(f"assistant.{name}", attributes=attributes) as span:
        try:
            yield span
        finally:
            timings[name] = int((time.monotonic() - start) * 1000)
            _step.reset(token)
            emit({"type": "step", "step": name, "state": "done", "ms": timings[name]})


def start_usage() -> dict:
    """Collect the model usage of the answer being computed (one dict per answer)."""
    usage: dict = {}
    _usage.set(usage)
    return usage


def current_usage() -> dict:
    return {step: dict(totals) for step, totals in (_usage.get() or {}).items()}


def record_llm_call(response: dict) -> dict:
    """Usage of one Ollama call: on the current span, and added to the step's totals.

    prompt_tokens is what the model had to read now; Ollama does not count the tokens it
    took from its cache, so a small number on a long prompt means the cache was used.
    """
    call = {
        "calls": 1,
        "prompt_tokens": response.get("prompt_eval_count", 0),
        "prompt_ms": int(response.get("prompt_eval_duration", 0) / 1e6),
        "output_tokens": response.get("eval_count", 0),
        "output_ms": int(response.get("eval_duration", 0) / 1e6),
        "load_ms": int(response.get("load_duration", 0) / 1e6),
    }
    span = trace.get_current_span()
    for key, value in call.items():
        span.set_attribute(f"llm.{key}", value)
    usage = _usage.get()
    if usage is not None:
        totals = usage.setdefault(_step.get(), dict.fromkeys(call, 0))
        for key, value in call.items():
            totals[key] += value
    return call


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
