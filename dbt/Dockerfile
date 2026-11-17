FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    DBT_PROFILES_DIR=/usr/app/dbt

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# The project is mounted at run time (see docker-compose.yml), so model changes
# do not require an image rebuild.
WORKDIR /usr/app/dbt

ENTRYPOINT ["dbt"]
