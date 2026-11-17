# Airflow image of the platform. Build context: repository root.
#   - Airflow + Cosmos in the main environment (Airflow version pinned so pip cannot move it)
#   - dbt in its own virtual environment (/opt/dbt_venv), as Cosmos recommends
#   - the ingestion package in its own virtual environment (/opt/ingestion_venv)
# The three dependency sets never conflict with each other.
FROM apache/airflow:3.3.1

ENV PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    PIP_NO_CACHE_DIR=1

USER root
RUN mkdir -p /opt/dbt_venv /opt/ingestion_venv /opt/ingestion \
    && chown -R airflow:root /opt/dbt_venv /opt/ingestion_venv /opt/ingestion
USER airflow

RUN pip install "apache-airflow==3.3.1" "astronomer-cosmos==1.16.0"

COPY --chown=airflow:root dbt/requirements.txt /tmp/dbt-requirements.txt
RUN python -m venv /opt/dbt_venv \
    && /opt/dbt_venv/bin/pip install -r /tmp/dbt-requirements.txt

COPY --chown=airflow:root ingestion/requirements.txt /tmp/ingestion-requirements.txt
RUN python -m venv /opt/ingestion_venv \
    && /opt/ingestion_venv/bin/pip install -r /tmp/ingestion-requirements.txt

COPY --chown=airflow:root ingestion/ /opt/ingestion/
RUN /opt/ingestion_venv/bin/pip install --no-deps /opt/ingestion

ENV CONTRACTS_DIR=/opt/ingestion/contracts \
    PYTHONPATH=/opt/airflow/include
