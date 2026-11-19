"""Prometheus metrics of the assistant, scraped at /metrics (profile observability).

Counts and durations only: no question text, no data value (those stay in the audit log,
behind database roles).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from assistant.schemas import Answer

ANSWERS = Counter(
    "assistant_answers_total", "Answers by status and prompt variant", ["status", "variant"]
)
ANSWER_SECONDS = Histogram(
    "assistant_answer_seconds",
    "Time to answer a question",
    buckets=[0.5, 5, 15, 30, 60, 120, 180, 300, 600, 900, 1800],
)
STEP_SECONDS = Histogram(
    "assistant_step_seconds",
    "Time of each step of an answer",
    ["step"],
    buckets=[0.01, 0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600],
)
NARRATIVE_CHECKS = Counter(
    "assistant_narrative_checks_total",
    "Narratives passed or replaced by the number and ranking checks",
    ["check"],
)
PLAN_CHANGES = Counter(
    "assistant_plan_changes_total",
    "Plans adjusted by grounding or repaired after validation",
    ["kind"],
)
LLM_CALLS = Counter("assistant_llm_calls_total", "Calls to the language model", ["step"])
LLM_TOKENS = Counter(
    "assistant_llm_tokens_total",
    "Tokens the model read (not counting its cache) and wrote",
    ["step", "kind"],
)
LLM_SECONDS = Counter(
    "assistant_llm_seconds_total", "Model time reading and writing", ["step", "kind"]
)


def observe(answer: Answer, variant: str) -> None:
    ANSWERS.labels(answer.status, variant).inc()
    ANSWER_SECONDS.observe(answer.duration_ms / 1000)
    for step, ms in answer.step_ms.items():
        STEP_SECONDS.labels(step).observe(ms / 1000)
    if answer.narrative_check != "not_needed":
        NARRATIVE_CHECKS.labels(answer.narrative_check).inc()
    for reason in answer.reasons:
        if reason.startswith("plan adjusted"):
            PLAN_CHANGES.labels("adjusted").inc()
        elif reason.startswith("plan repaired"):
            PLAN_CHANGES.labels("repaired").inc()
    for step, usage in answer.llm_usage.items():
        LLM_CALLS.labels(step).inc(usage.get("calls", 0))
        LLM_TOKENS.labels(step, "read").inc(usage.get("prompt_tokens", 0))
        LLM_TOKENS.labels(step, "written").inc(usage.get("output_tokens", 0))
        LLM_SECONDS.labels(step, "read").inc(usage.get("prompt_ms", 0) / 1000)
        LLM_SECONDS.labels(step, "written").inc(usage.get("output_ms", 0) / 1000)
