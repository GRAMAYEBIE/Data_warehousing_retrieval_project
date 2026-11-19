-- Keep the published BI views in memory (pg_prewarm, loaded by shared_preload_libraries).
-- Idempotent: safe to apply on an existing warehouse
--   docker compose exec -T postgres psql -U postgres -d warehouse -f /docker-entrypoint-initdb.d/06_prewarm.sql
-- publisher loads the views after each publication; the assistant's read-only role loads
-- the ones it queries when it starts. pg_prewarm only reads: it needs SELECT on the
-- relation, which both roles already have, and EXECUTE on the function, granted here.
-- The extension lives in its own schema `util`: `public` stays closed to every role
-- (01_schemas.sql), so only the two roles below can see the function.
CREATE SCHEMA IF NOT EXISTS util;
REVOKE ALL ON SCHEMA util FROM PUBLIC;
CREATE EXTENSION IF NOT EXISTS pg_prewarm SCHEMA util;
DO $$
BEGIN
    IF (SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'pg_prewarm')
        <> 'util' THEN
        ALTER EXTENSION pg_prewarm SET SCHEMA util;
    END IF;
END $$;
GRANT USAGE ON SCHEMA util TO publisher, ai_reader;
REVOKE EXECUTE ON FUNCTION util.pg_prewarm(regclass, text, text, bigint, bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION util.pg_prewarm(regclass, text, text, bigint, bigint)
    TO publisher, ai_reader;
