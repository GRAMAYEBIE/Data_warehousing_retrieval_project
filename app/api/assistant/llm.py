"""Ollama client. The model plans (JSON constrained by a schema) and explains; it never
computes and never writes SQL. Every failure becomes ModelUnavailable, so the API can
answer with a clear degraded message instead of an error page."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

from assistant import telemetry

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
PLAN_MAX_TOKENS = 400  # a report request with three extra charts stays below this


class ModelUnavailable(Exception):
    pass


class MalformedOutput(Exception):
    def __init__(self, message: str, syntax: bool = False) -> None:
        super().__init__(message)
        self.syntax = syntax  # True: not JSON at all; False: JSON that is not a valid plan


class Ollama:
    """Prompts are built so the system prompt is the same on every call of a kind (rules,
    vocabulary, examples) and everything that changes is in the user message: Ollama then
    reuses the already-read prefix instead of reading about 1,600 tokens again (on the
    development CPU, about 4 tokens per second)."""

    def __init__(
        self,
        url: str,
        model: str,
        timeout_s: float,
        threads: int = 0,
        keep_alive: str = "-1",
        output_mode: str = "free",
        concurrency: int = 1,
    ) -> None:
        self.url, self.model = url, model
        self.threads, self.keep_alive = threads, keep_alive
        self.output_mode = output_mode
        self.http = httpx.Client(timeout=timeout_s)
        # Calls to the model at the same time. On a CPU host, two calls share the cores and
        # both slow down (observed: the start-up warm-up and the first question together
        # took more than 15 minutes, and PostgreSQL queries slowed down with them); on a
        # GPU host it can be raised (LLM_MAX_CONCURRENCY).
        self.slots = threading.BoundedSemaphore(max(1, concurrency))

    def available(self) -> bool:
        try:
            tags = self.http.get(f"{self.url}/api/tags", timeout=5).json()
        except httpx.HTTPError:
            return False
        return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))

    def chat(
        self,
        system: str,
        user: str,
        schema: dict | str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        options: dict = {"temperature": 0, "num_ctx": 4096}
        if self.threads:
            options["num_thread"] = self.threads
        if max_tokens:
            options["num_predict"] = max_tokens
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": keep_alive_value(self.keep_alive),  # -1: the model stays loaded
            "options": options,
        }
        if schema is not None:
            body["format"] = schema  # structured output: the reply must match the schema
        try:
            with self.slots:  # waits for its turn; the wait counts in the caller's timings
                response = self.http.post(f"{self.url}/api/chat", json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Ollama explains a refused request in its body: keep it for the audit log.
            detail = exc.response.text[:200].strip()
            raise ModelUnavailable(
                f"language model refused the request (HTTP {exc.response.status_code}): {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"language model unavailable: {type(exc).__name__}") from exc
        payload = response.json()
        telemetry.record_llm_call(payload)
        return payload["message"]["content"]

    def planner_system(self, system: str, model_cls: type[BaseModel]) -> str:
        """Outside "schema" mode the decoder does not enforce the schema, so the fields are
        given as text: a compact list generated from the Pydantic model (one source of
        truth), not the raw JSON schema, which a 3B model tended to copy or fill entirely
        (observed: a 1,500-character plan cut at the token limit). It is part of the system
        prompt: Ollama reads it once and keeps it cached."""
        if self.output_mode == "schema":
            return system
        return (
            f"{system}\n\nReply with ONE JSON object only. Fields (write only the ones the "
            "question needs; every other field keeps its default):\n"
            + compact_fields(model_cls.model_json_schema())
        )

    def warm_up(self, system: str) -> None:
        """Read a system prompt into Ollama's cache (one output token)."""
        self.chat(system, "CONTEXT:\nwarm-up\n\nQUESTION: warm-up", max_tokens=1)

    def structured(self, system: str, user: str, model_cls: type[BaseModel]) -> BaseModel:
        """A plan the code can trust, whatever the decoding mode.

        output_mode "schema": Ollama constrains decoding to the JSON schema; "json": generic
        JSON grammar; "free" (default): no constraint. Measured on the development CPU with
        the same two questions and identical plans: schema 69 s to 9 min per plan (each token
        checked against the whole schema), json 29 to 95 s, free 22 to 24 s. In every mode
        the reply is validated by Pydantic (then by the policy validator), and an invalid
        reply gets one repair attempt in which the model sees the validation error; a second
        failure is MalformedOutput.
        """
        fmt = {"schema": model_cls.model_json_schema(), "json": "json"}.get(self.output_mode)
        system = self.planner_system(system, model_cls)
        # A plan is 20 to 60 tokens; without a decoding constraint nothing else stops a model
        # that keeps writing after its JSON, so the output is capped.
        raw = self.chat(system, user, schema=fmt, max_tokens=PLAN_MAX_TOKENS)
        try:
            return parse_plan(raw, model_cls)
        except MalformedOutput as first:
            repair = (
                f"{user}\n\nYour previous reply was not a valid plan ({first}). "
                "Reply again with only the corrected JSON object."
            )
            # A JSON syntax error is repaired under Ollama's JSON grammar, which makes a
            # second syntax error impossible (observed in the baseline evaluation: the same
            # missing comma twice); the fast free decoding stays the normal path.
            retry_fmt = "json" if first.syntax and fmt is None else fmt
            fixed = self.chat(system, repair, schema=retry_fmt, max_tokens=PLAN_MAX_TOKENS)
            return parse_plan(fixed, model_cls)


def compact_fields(schema: dict) -> str:
    """'- intent: trend|compare|... (required)' lines from a JSON schema, nested objects
    and lists of objects inline, so a small model sees names and allowed values only."""
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        if "$ref" in node:
            return resolve(defs[node["$ref"].split("/")[-1]])
        if "anyOf" in node:  # Optional[X]: keep X
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            return resolve(options[0]) if options else node
        if "allOf" in node and len(node["allOf"]) == 1:
            return resolve(node["allOf"][0])
        return node

    def kind(node: dict) -> str:
        node = resolve(node)
        if "enum" in node:
            return "|".join(map(str, node["enum"]))
        if "const" in node:
            return str(node["const"])
        if node.get("type") == "object" and "properties" in node:
            inner = ", ".join(f"{k}: {kind(v)}" for k, v in node["properties"].items())
            return "{" + inner + "}"
        if node.get("type") == "array":
            return f"[{kind(node.get('items', {}))}]"
        return node.get("type", "value")

    required = set(schema.get("required", []))
    return "\n".join(
        f"- {name}: {kind(prop)}" + (" (required)" if name in required else "")
        for name, prop in schema.get("properties", {}).items()
    )


def parse_plan(raw: str, model_cls: type[BaseModel]) -> BaseModel:
    """The first JSON object of the reply (models sometimes wrap it in text or a code
    fence), validated against the Pydantic model."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise MalformedOutput(f"no JSON object in the reply (began: {raw[:160]!r})", True)
    try:
        return model_cls.model_validate(json.loads(raw[start : end + 1]))
    except json.JSONDecodeError as exc:
        raise MalformedOutput(
            f"invalid JSON: {exc.msg} at character {exc.pos} (reply began: {raw[:160]!r})", True
        ) from exc
    except ValidationError as exc:
        # Field and reason, so the repair attempt knows exactly what to change.
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'plan'}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise MalformedOutput(f"reply does not match {model_cls.__name__}: {problems}") from exc


def keep_alive_value(value: str) -> int | str:
    """Ollama wants a number of seconds (-1: forever) or a duration with a unit ("30m");
    the string "-1" is refused ("missing unit in duration")."""
    try:
        return int(value)
    except ValueError:
        return value


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def planning_prompt(variant: str, catalog_summary: str) -> str:
    """System prompt of the planner: identical for every question (cacheable prefix)."""
    return load_prompt(f"plan_{variant}").format(catalog=catalog_summary)


def planning_message(context: str, question: str, retrieved: str = "") -> str:
    """User message of the planner: what changes from one question to the next (context,
    retrieved vocabulary and examples, question), after the cached system prompt."""
    middle = f"\n\n{retrieved}" if retrieved else ""
    return f"CONTEXT:\n{context}{middle}\n\nQUESTION: {question}"
