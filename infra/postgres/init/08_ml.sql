-- Machine learning (wave 7, Compose profile ml): the forecasting role, the ml schema it
-- writes, and the MLflow tracking database. Passwords come from the container environment.
-- Idempotent: it runs on the first start of a new volume, and can be applied by hand to an
-- existing warehouse (README, "Demand forecast").
\getenv forecaster_pw FORECASTER_PASSWORD
\getenv mlflow_db_pw MLFLOW_DB_PASSWORD
\getenv warehouse_db POSTGRES_DB

SELECT format('CREATE ROLE forecaster LOGIN PASSWORD %L', :'forecaster_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'forecaster') \gexec
SELECT format('CREATE ROLE mlflow LOGIN PASSWORD %L', :'mlflow_db_pw')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mlflow') \gexec

-- MLflow's runs, parameters, metrics and model registry: a tool database, apart from the
-- business data like airflow_meta and superset_meta. Artefacts go to the object store.
SELECT 'CREATE DATABASE mlflow_meta OWNER mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow_meta') \gexec
REVOKE CONNECT ON DATABASE mlflow_meta FROM PUBLIC;

CREATE SCHEMA IF NOT EXISTS ml;
COMMENT ON SCHEMA ml IS 'Forecasts of recorded trips, their evaluation and run metadata. '
    'Written by forecaster only; estimates, never governed metrics.';

-- forecaster: reads the published layer (like the dashboards), writes the ml schema only.
GRANT CONNECT ON DATABASE :"warehouse_db" TO forecaster;
GRANT USAGE ON SCHEMA analytics TO forecaster;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO forecaster;
ALTER DEFAULT PRIVILEGES FOR ROLE publisher IN SCHEMA analytics GRANT SELECT ON TABLES TO forecaster;
GRANT USAGE, CREATE ON SCHEMA ml TO forecaster;

-- The dashboards and the assistant may read the forecasts, nothing else in ml.
GRANT USAGE ON SCHEMA ml TO superset_reader, ai_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE forecaster IN SCHEMA ml
    GRANT SELECT ON TABLES TO superset_reader, ai_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ml TO superset_reader, ai_reader;

-- Monitoring reads the forecast-against-actual verdicts (alert ForecastDrift).
GRANT USAGE ON SCHEMA ml TO metrics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE forecaster IN SCHEMA ml GRANT SELECT ON TABLES TO metrics_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ml TO metrics_reader;
