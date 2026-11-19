-- Read-only role of the observability stack (postgres-exporter and Grafana).
-- Idempotent: safe to apply on an existing warehouse
--   docker compose exec -T -e METRICS_READER_PASSWORD postgres psql -U postgres -d warehouse \
--     -f /docker-entrypoint-initdb.d/07_observability.sql
-- It reads database statistics (pg_monitor) and the operational state of the platform;
-- it cannot read trips, bronze, silver or gold, and cannot write anything.
\getenv metrics_reader_pw METRICS_READER_PASSWORD

SELECT format('CREATE ROLE metrics_reader LOGIN PASSWORD %L', :'metrics_reader_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metrics_reader')\gexec
ALTER ROLE metrics_reader PASSWORD :'metrics_reader_pw';
ALTER ROLE metrics_reader SET default_transaction_read_only = on;
ALTER ROLE metrics_reader SET statement_timeout = '15s';

GRANT pg_monitor TO metrics_reader;
GRANT CONNECT ON DATABASE warehouse TO metrics_reader;
GRANT USAGE ON SCHEMA ops, analytics TO metrics_reader;
GRANT SELECT ON ops.pipeline_runs, ops.pipeline_signals, ops.dbt_test_results,
    ops.publications, ops.ingestion_manifest TO metrics_reader;
GRANT SELECT ON ops.ai_audit_log TO metrics_reader;
-- Only these two published tables (status and reconciliation), not the business
-- aggregates; the publication task grants them again each time it recreates them.
GRANT SELECT ON analytics.pipeline_status, analytics.recon_bronze_silver TO metrics_reader;
