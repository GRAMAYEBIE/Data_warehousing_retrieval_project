-- Least-privilege roles (exam Q11). Passwords come from the container environment,
-- never from this file.
\getenv loader_pw LOADER_PASSWORD
\getenv transformer_pw TRANSFORMER_PASSWORD
\getenv publisher_pw PUBLISHER_PASSWORD
\getenv superset_reader_pw SUPERSET_READER_PASSWORD
\getenv ai_reader_pw AI_READER_PASSWORD
\getenv ai_audit_writer_pw AI_AUDIT_WRITER_PASSWORD
\getenv airflow_db_pw AIRFLOW_DB_PASSWORD
\getenv superset_db_pw SUPERSET_DB_PASSWORD
\getenv warehouse_db POSTGRES_DB

CREATE ROLE loader          LOGIN PASSWORD :'loader_pw';
CREATE ROLE transformer     LOGIN PASSWORD :'transformer_pw';
CREATE ROLE publisher       LOGIN PASSWORD :'publisher_pw';
CREATE ROLE superset_reader LOGIN PASSWORD :'superset_reader_pw';
CREATE ROLE ai_reader       LOGIN PASSWORD :'ai_reader_pw';
CREATE ROLE ai_audit_writer LOGIN PASSWORD :'ai_audit_writer_pw';

-- Only the warehouse roles may connect to the warehouse database.
REVOKE CONNECT ON DATABASE :"warehouse_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"warehouse_db"
    TO loader, transformer, publisher, superset_reader, ai_reader, ai_audit_writer;

-- loader: writes bronze and ops, nothing else.
GRANT USAGE, CREATE ON SCHEMA bronze TO loader;
GRANT USAGE, CREATE ON SCHEMA ops TO loader;

-- transformer (dbt): reads bronze and ops, writes silver and gold.
GRANT USAGE ON SCHEMA bronze, ops TO transformer;
GRANT USAGE, CREATE ON SCHEMA silver, gold TO transformer;
ALTER DEFAULT PRIVILEGES FOR ROLE loader IN SCHEMA bronze GRANT SELECT ON TABLES TO transformer;
ALTER DEFAULT PRIVILEGES FOR ROLE loader IN SCHEMA ops GRANT SELECT ON TABLES TO transformer;

-- publisher: reads gold and ops, owns the published layer and the metric catalogue.
GRANT USAGE ON SCHEMA gold, ops TO publisher;
GRANT USAGE, CREATE ON SCHEMA analytics, semantic TO publisher;
ALTER DEFAULT PRIVILEGES FOR ROLE transformer IN SCHEMA gold GRANT SELECT ON TABLES TO publisher;
ALTER DEFAULT PRIVILEGES FOR ROLE loader IN SCHEMA ops GRANT SELECT ON TABLES TO publisher;

-- superset_reader: SELECT on the published layer only.
GRANT USAGE ON SCHEMA analytics TO superset_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE publisher IN SCHEMA analytics GRANT SELECT ON TABLES TO superset_reader;

-- ai_reader: SELECT on the published layer and the metric catalogue, strictly read-only,
-- with a hard statement timeout. The only role used to run LLM-planned queries.
GRANT USAGE ON SCHEMA analytics, semantic TO ai_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE publisher IN SCHEMA analytics GRANT SELECT ON TABLES TO ai_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE publisher IN SCHEMA semantic GRANT SELECT ON TABLES TO ai_reader;
ALTER ROLE ai_reader SET statement_timeout = '10s';
ALTER ROLE ai_reader SET default_transaction_read_only = on;
ALTER ROLE ai_reader SET idle_in_transaction_session_timeout = '30s';

-- ai_audit_writer: may only append to the AI audit log (table created with the AI service).
GRANT USAGE ON SCHEMA ops TO ai_audit_writer;

-- Tool metadata databases: same server, kept apart from business data.
CREATE ROLE airflow  LOGIN PASSWORD :'airflow_db_pw';
CREATE ROLE superset LOGIN PASSWORD :'superset_db_pw';
CREATE DATABASE airflow_meta  OWNER airflow;
CREATE DATABASE superset_meta OWNER superset;
REVOKE CONNECT ON DATABASE airflow_meta  FROM PUBLIC;
REVOKE CONNECT ON DATABASE superset_meta FROM PUBLIC;
