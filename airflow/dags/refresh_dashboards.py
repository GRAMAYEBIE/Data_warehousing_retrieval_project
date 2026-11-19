"""Refresh Superset from the current publication (manual trigger).

The monthly pipeline does this itself after each publication. Trigger this DAG when
Superset was not running at that moment, or after a change of metric definitions: it
syncs the metric catalogue and the certified datasets (which invalidates cached chart
results), then rebuilds the six dashboards and their "So what?" texts.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from nyc_taxi_ops import bi_refresh

WAREHOUSE_CONN = "warehouse_publisher"
DBT_PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt"))


def refresh(**_) -> str:
    connection = PostgresHook.get_connection(WAREHOUSE_CONN)
    env = bi_refresh.command_env(
        connection.host,
        connection.port or 5432,
        connection.schema,
        connection.login,
        connection.password,
    )
    result = bi_refresh.refresh(env, DBT_PROJECT_DIR / "target" / "semantic_manifest.json")
    if result == bi_refresh.SUPERSET_DOWN:
        raise RuntimeError("Superset is not running: start the bi profile, then trigger again")
    return result


with DAG(
    dag_id="refresh_dashboards",
    description="Sync Superset datasets and rebuild the dashboards from the current publication",
    schedule=None,
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "AYEBIE GRAM MESCHAC", "retries": 0},
    tags=["nyc-taxi", "superset"],
    doc_md=__doc__,
) as dag:
    PythonOperator(
        task_id="refresh_dashboards",
        python_callable=refresh,
        execution_timeout=timedelta(minutes=45),
    )
