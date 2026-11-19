-- Audit log of the AI assistant (exam Q9: logs of validation, guardrails and provenance).
-- Idempotent: safe to apply on an existing warehouse
--   docker compose exec -T postgres psql -U postgres -d warehouse -f /docker-entrypoint-initdb.d/05_ai_audit.sql
-- Owned by loader (owner of ops). The assistant writes with ai_audit_writer, which can
-- only INSERT here; it reads data with ai_reader, which cannot write anything.
SET ROLE loader;

CREATE TABLE IF NOT EXISTS ops.ai_audit_log (
    event_id         bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id       text        NOT NULL,
    question         text        NOT NULL,
    prompt_variant   text,
    model            text,
    plan             jsonb,          -- structured plan produced by the LLM
    verdict          text        NOT NULL
        CHECK (verdict IN ('answered', 'clarify', 'rejected', 'unsupported', 'empty',
                           'model_unavailable', 'query_failed', 'draft_created',
                           'draft_published')),
    reasons          jsonb,          -- validation or guardrail reasons
    rendered_sql     text,           -- SQL built from templates (never written by the LLM)
    row_count        integer,
    narrative_check  text,           -- passed | replaced (a number not in the result)
    duration_ms      integer,
    created_at       timestamptz NOT NULL DEFAULT now()
);
-- Observability: duration of each step and the OpenTelemetry trace of the answer.
ALTER TABLE ops.ai_audit_log ADD COLUMN IF NOT EXISTS step_ms jsonb;   -- {"plan": 41234, ...}
ALTER TABLE ops.ai_audit_log ADD COLUMN IF NOT EXISTS trace_id text;   -- 32 hex characters
-- Model usage per step: calls, tokens read now (cached ones not counted), tokens written.
ALTER TABLE ops.ai_audit_log ADD COLUMN IF NOT EXISTS llm_usage jsonb;
CREATE INDEX IF NOT EXISTS ai_audit_log_session_idx ON ops.ai_audit_log (session_id, created_at);
CREATE INDEX IF NOT EXISTS ai_audit_log_trace_idx ON ops.ai_audit_log (trace_id);
COMMENT ON TABLE ops.ai_audit_log IS
    'One row per assistant step: question, plan, validation verdict, rendered SQL, result size, narrative check.';

GRANT INSERT ON ops.ai_audit_log TO ai_audit_writer;
GRANT USAGE ON SEQUENCE ops.ai_audit_log_event_id_seq TO ai_audit_writer;
GRANT SELECT ON ops.ai_audit_log TO publisher, transformer;

RESET ROLE;
