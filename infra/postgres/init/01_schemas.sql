-- Warehouse schemas (medallion + serving + operations).
-- Runs once, on first start of the postgres volume, in the warehouse database.

CREATE SCHEMA IF NOT EXISTS bronze;     -- immutable, source-aligned rows + ingestion metadata
CREATE SCHEMA IF NOT EXISTS silver;     -- typed, cleaned, flagged trips
CREATE SCHEMA IF NOT EXISTS gold;       -- star schema + additive aggregates
CREATE SCHEMA IF NOT EXISTS analytics;  -- published materialized views (the only layer BI/AI may read)
CREATE SCHEMA IF NOT EXISTS semantic;   -- governed metric catalogue
CREATE SCHEMA IF NOT EXISTS ops;        -- manifests, pipeline runs, signals, audit logs

COMMENT ON SCHEMA bronze IS 'Immutable source-aligned records plus ingestion metadata. Written by loader only.';
COMMENT ON SCHEMA silver IS 'Typed, standardised trips with quality flags. Written by dbt (transformer).';
COMMENT ON SCHEMA gold IS 'Star schema (fct_trip + dimensions) and additive aggregates. Written by dbt (transformer).';
COMMENT ON SCHEMA analytics IS 'Published layer: refreshed only after a fully green dbt build. Read by Superset and the AI assistant.';
COMMENT ON SCHEMA semantic IS 'Governed metric catalogue generated from the dbt metric YAML.';
COMMENT ON SCHEMA ops IS 'Operational metadata: ingestion manifest, pipeline runs and signals, AI audit log.';

-- Nobody gets implicit rights: everything is granted explicitly in 02_roles.sql.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
