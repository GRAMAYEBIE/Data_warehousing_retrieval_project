"""Demand forecast after each publication (wave 7).

Scheduled on the asset `analytics_published`: each time a month is published (monthly
batch or stream), this DAG
1. checks the published forecast of that month against what was recorded (error, bias,
   80 % coverage, drift against what the backtests promised), before it is replaced;
2. backtests the seasonal baseline and the LightGBM challenger on the last three months,
   keeps the champion, records the run in MLflow and publishes the forecast of the next
   month to the ml schema.
The loop then repeats with every new month. Can also be triggered by hand.

Needs the profile ml (MLflow) to be running; the task fails clearly otherwise.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from nyc_taxi_ops.assets import ANALYTICS_PUBLISHED

FORECAST_ENV = {
    "PGHOST": "postgres",
    "PGPORT": "5432",
    "PGDATABASE": os.environ.get("INGEST_PGDATABASE", "warehouse"),
    "PGUSER": "forecaster",
    "FORECASTER_PASSWORD": os.environ.get("FORECASTER_PASSWORD", ""),
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    "GIT_PYTHON_REFRESH": "quiet",  # the run records a fingerprint of the code instead
}

with DAG(
    dag_id="demand_forecast",
    description="Check last forecast against actual, then train, choose, track, publish",
    schedule=[ANALYTICS_PUBLISHED],
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "AYEBIE GRAM MESCHAC",
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["nyc-taxi", "ml", "mlflow"],
    doc_md=__doc__,
) as dag:
    BashOperator(
        task_id="check_train_publish",
        bash_command="/opt/forecast_venv/bin/python -m forecasting",
        env=FORECAST_ENV,
        append_env=True,
        execution_timeout=timedelta(minutes=45),
    )
