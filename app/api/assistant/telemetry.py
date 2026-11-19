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
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

tracer = trace.get_tracer("assistant")
_configured = False


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

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    _configured = True


@contextmanager
def step(name: str, timings: dict[str, int], **attributes) -> Iterator[trace.Span]:
    """One step of the answer: a span, and its duration in milliseconds in `timings`."""
    start = time.monotonic()
    with tracer.start_as_current_span(f"assistant.{name}", attributes=attributes) as span:
        try:
            yield span
        finally:
            timings[name] = int((time.monotonic() - start) * 1000)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
