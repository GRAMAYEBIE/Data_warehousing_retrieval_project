"""Settings from the environment. No secret is stored in code."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_name: str
    reader_password: str  # ai_reader: SELECT on analytics and semantic, read-only, 10 s
    audit_password: str  # ai_audit_writer: INSERT on ops.ai_audit_log only
    ollama_url: str
    model: str
    prompt_variant: str
    api_token: str
    max_rows: int
    llm_timeout_s: float
    llm_threads: int  # 0: Ollama decides
    llm_keep_alive: str  # "-1": keep the model loaded
    llm_output_mode: str  # schema | json | free (see Ollama.structured)
    superset_url: str
    superset_user: str
    superset_password: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_host=os.environ.get("PGHOST", "postgres"),
            db_name=os.environ.get("PGDATABASE", "warehouse"),
            reader_password=os.environ["AI_READER_PASSWORD"],
            audit_password=os.environ["AI_AUDIT_WRITER_PASSWORD"],
            ollama_url=os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/"),
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
            prompt_variant=os.environ.get("PROMPT_VARIANT", "v3_structured_examples"),
            api_token=os.environ["API_TOKEN"],
            max_rows=int(os.environ.get("ASSISTANT_MAX_ROWS", "5000")),
            llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "600")),
            llm_threads=int(os.environ.get("OLLAMA_NUM_THREAD", "0")),
            llm_keep_alive=os.environ.get("OLLAMA_KEEP_ALIVE", "-1"),
            llm_output_mode=os.environ.get("LLM_OUTPUT_MODE", "free"),
            superset_url=os.environ.get("SUPERSET_URL", "http://superset:8088").rstrip("/"),
            superset_user=os.environ.get("SUPERSET_AI_USER", "ai_builder"),
            superset_password=os.environ.get("SUPERSET_AI_PASSWORD", ""),
        )
