-- Pipeline operations: runs, publications, dbt test results and operational signals.
-- Idempotent: safe to apply on an existing warehouse
--   docker compose exec -T postgres psql -U postgres -d warehouse -f /docker-entrypoint-initdb.d/04_ops_pipeline.sql
-- Tables are owned by loader (owner of ops). publisher records what it publishes and
-- measures; it cannot change the ingestion manifest.
SET ROLE loader;

-- One row per orchestrated run of the monthly pipeline.
CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id         text        PRIMARY KEY,           -- Airflow dag_run run_id
    dag_id         text        NOT NULL,
    source_month   date        NOT NULL,
    forced         boolean     NOT NULL DEFAULT false,
    status         text        NOT NULL
        CHECK (status IN ('running', 'published', 'nothing_new', 'failed')),
    published      boolean     NOT NULL DEFAULT false,
    message        text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);
COMMENT ON TABLE ops.pipeline_runs IS
    'One row per run of the monthly pipeline: month, outcome, and whether analytics was published.';

-- One row per publication of the analytics layer (the publication gate).
CREATE TABLE IF NOT EXISTS ops.publications (
    publication_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id          text        NOT NULL,
    published_at    timestamptz NOT NULL DEFAULT now(),
    tables          jsonb       NOT NULL,             -- {"agg_trips_daily": rows, ...}
    batches         jsonb       NOT NULL              -- {"2025-01-01": "<batch_id>", ...}
);
COMMENT ON TABLE ops.publications IS
    'Each atomic publication of gold tables to analytics, with the batches it contains.';

-- Result of every dbt test executed by the pipeline.
CREATE TABLE IF NOT EXISTS ops.dbt_test_results (
    run_id          text        NOT NULL,
    unique_id       text        NOT NULL,
    status          text        NOT NULL,             -- pass, fail, error, warn, skipped
    failures        integer,
    execution_time  double precision,
    message         text,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, unique_id)
);
COMMENT ON TABLE ops.dbt_test_results IS 'Result of each dbt test run by the orchestrated pipeline.';

-- Operational signals measured at the end of each run (exam Q5.4).
CREATE TABLE IF NOT EXISTS ops.pipeline_signals (
    run_id        text        NOT NULL,
    source_month  date        NOT NULL,
    signal_name   text        NOT NULL,
    signal_value  numeric,
    unit          text,
    threshold     text,
    status        text        NOT NULL CHECK (status IN ('ok', 'warn', 'fail')),
    details       jsonb,
    measured_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, signal_name)
);
COMMENT ON TABLE ops.pipeline_signals IS
    'Freshness, volume change, rejected-row rate, dbt test pass rate, late data and duration per run.';

GRANT SELECT, INSERT, UPDATE ON ops.pipeline_runs, ops.publications,
    ops.dbt_test_results, ops.pipeline_signals TO publisher;
GRANT SELECT ON ops.pipeline_runs, ops.publications, ops.dbt_test_results,
    ops.pipeline_signals TO transformer;
-- ingestion_manifest existed before the default privileges of 02_roles.sql applied to it.
GRANT SELECT ON ops.ingestion_manifest TO transformer, publisher;

RESET ROLE;
