"""Airflow assets shared by the DAGs.

ANALYTICS_PUBLISHED is updated by the monthly pipeline's publication task, only when it
publishes (a run with nothing new skips that task and emits nothing). The demand forecast
DAG is scheduled on it, so a new publication is followed by a new forecast.
"""

from airflow.sdk import Asset

# The table that records each publication (a postgres:// asset names database/schema/table).
ANALYTICS_PUBLISHED = Asset(
    name="analytics_published",
    uri="postgres://postgres:5432/warehouse/analytics/pipeline_status",
)
