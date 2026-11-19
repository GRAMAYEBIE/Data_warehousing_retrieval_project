"""Ollama client. The model plans (JSON constrained by a schema) and explains; it never
computes and never writes SQL. Every failure becomes ModelUnavailable, so the API can
answer with a clear degraded message instead of an error page."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ValidationError

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


class ModelUnavailable(Exception):
    pass


class MalformedOutput(Exception):
    pass


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
    ) -> None:
        self.url, self.model = url, model
        self.threads, self.keep_alive = threads, keep_alive
        self.output_mode = output_mode
        self.http = httpx.Client(timeout=timeout_s)

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
        return response.json()["message"]["content"]

    def planner_system(self, system: str, model_cls: type[BaseModel]) -> str:
        """Outside "schema" mode the decoder does not enforce the schema, so it is given as
        text. It is part of the system prompt: Ollama reads it once and keeps it cached."""
        if self.output_mode == "schema":
            return system
        schema = json.dumps(model_cls.model_json_schema(), separators=(",", ":"))
        return f"{system}\n\nReply with ONE JSON object only, matching this JSON schema:\n{schema}"

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
        raw = self.chat(system, user, schema=fmt)
        try:
            return parse_plan(raw, model_cls)
        except MalformedOutput as first:
            repair = (
                f"{user}\n\nYour previous reply was not a valid plan ({first}). "
                "Reply again with only the corrected JSON object."
            )
            return parse_plan(self.chat(system, repair, schema=fmt), model_cls)


def parse_plan(raw: str, model_cls: type[BaseModel]) -> BaseModel:
    """The first JSON object of the reply (models sometimes wrap it in text or a code
    fence), validated against the Pydantic model."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise MalformedOutput(f"no JSON object in the reply: {raw[:120]!r}")
    try:
        return model_cls.model_validate(json.loads(raw[start : end + 1]))
    except json.JSONDecodeError as exc:
        raise MalformedOutput(f"invalid JSON: {exc.msg} at character {exc.pos}") from exc
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


def planning_message(context: str, question: str) -> str:
    """User message of the planner: what changes from one question to the next."""
    return f"CONTEXT:\n{context}\n\nQUESTION: {question}"
