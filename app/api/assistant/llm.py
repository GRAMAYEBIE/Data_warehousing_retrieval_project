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
    ) -> None:
        self.url, self.model = url, model
        self.threads, self.keep_alive = threads, keep_alive
        self.http = httpx.Client(timeout=timeout_s)

    def available(self) -> bool:
        try:
            tags = self.http.get(f"{self.url}/api/tags", timeout=5).json()
        except httpx.HTTPError:
            return False
        return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))

    def chat(
        self, system: str, user: str, schema: dict | None = None, max_tokens: int | None = None
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

    def structured(self, system: str, user: str, model_cls: type[BaseModel]) -> BaseModel:
        raw = self.chat(system, user, schema=model_cls.model_json_schema())
        try:
            return model_cls.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise MalformedOutput(
                f"model output does not match {model_cls.__name__}: {exc}"
            ) from exc


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
