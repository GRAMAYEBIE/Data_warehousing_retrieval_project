# Streaming service (profile stream): replays a monthly file into Kafka (produce) and writes
# the provisional trips to PostgreSQL (consume). See src/stream/__main__.py.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10 \
    STREAM_CACHE=/cache

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
RUN pip install --no-deps .

RUN useradd --create-home stream && mkdir -p /cache && chown stream /cache
USER stream

ENTRYPOINT ["python", "-m", "stream"]
