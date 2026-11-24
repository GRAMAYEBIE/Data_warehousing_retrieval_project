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
RUN mkdir -p /opt/dbt_venv /opt/ingestion_venv /opt/ingestion /opt/dbt_deps \
    && chown -R airflow:root /opt/dbt_venv /opt/ingestion_venv /opt/ingestion /opt/dbt_deps
USER airflow

RUN pip install "apache-airflow==3.3.1" "astronomer-cosmos==1.16.0"

COPY --chown=airflow:root dbt/requirements.txt /tmp/dbt-requirements.txt
RUN python -m venv /opt/dbt_venv \
    && /opt/dbt_venv/bin/pip install -r /tmp/dbt-requirements.txt

# dbt packages installed once, on the container's own disk: Cosmos tasks read them in
# place instead of copying them from the mounted project before every task.
COPY --chown=airflow:root dbt/packages.yml dbt/package-lock.yml /opt/dbt_deps/
# (dbt deps deletes and recreates the install folder, so it sits in a folder airflow owns)
RUN printf 'name: deps_only\nversion: "1.0"\nconfig-version: 2\nprofile: none\npackages-install-path: /opt/dbt_deps/dbt_packages\n' \
        > /opt/dbt_deps/dbt_project.yml \
    && cd /opt/dbt_deps && /opt/dbt_venv/bin/dbt deps --quiet \
    && ls /opt/dbt_deps/dbt_packages

COPY --chown=airflow:root ingestion/requirements.txt /tmp/ingestion-requirements.txt
RUN python -m venv /opt/ingestion_venv \
    && /opt/ingestion_venv/bin/pip install -r /tmp/ingestion-requirements.txt

COPY --chown=airflow:root ingestion/ /opt/ingestion/
RUN /opt/ingestion_venv/bin/pip install --no-deps /opt/ingestion

# Demand forecast (wave 7) in its own virtual environment too; LightGBM needs OpenMP.
USER root
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/forecast_venv /opt/forecast && chown -R airflow:root /opt/forecast_venv /opt/forecast
USER airflow
COPY --chown=airflow:root ml/requirements.txt /tmp/forecast-requirements.txt
RUN python -m venv /opt/forecast_venv \
    && /opt/forecast_venv/bin/pip install -r /tmp/forecast-requirements.txt
COPY --chown=airflow:root ml/ /opt/forecast/
RUN /opt/forecast_venv/bin/pip install --no-deps /opt/forecast

ENV CONTRACTS_DIR=/opt/ingestion/contracts \
    PYTHONPATH=/opt/airflow/include \
    DBT_PACKAGES_INSTALL_PATH=/opt/dbt_deps/dbt_packages
