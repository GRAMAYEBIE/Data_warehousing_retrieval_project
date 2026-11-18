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
    def __init__(self, url: str, model: str, timeout_s: float) -> None:
        self.url, self.model = url, model
        self.http = httpx.Client(timeout=timeout_s)

    def available(self) -> bool:
        try:
            tags = self.http.get(f"{self.url}/api/tags", timeout=5).json()
        except httpx.HTTPError:
            return False
        return any(m.get("name", "").startswith(self.model) for m in tags.get("models", []))

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
        }
        if schema is not None:
            body["format"] = schema  # structured output: the reply must match the schema
        try:
            response = self.http.post(f"{self.url}/api/chat", json=body)
            response.raise_for_status()
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


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def planning_prompt(variant: str, catalog_summary: str, today_context: str) -> str:
    return load_prompt(f"plan_{variant}").format(catalog=catalog_summary, context=today_context)
