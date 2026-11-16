FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    CONTRACTS_DIR=/app/contracts

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY contracts ./contracts
COPY tests ./tests
RUN pip install --no-deps .

RUN useradd --create-home ingest
USER ingest

ENTRYPOINT ["python", "-m", "ingestion.cli"]
