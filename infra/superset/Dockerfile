# Superset image of the platform: the official 6.1.0 image plus the PostgreSQL driver,
# which recent official images no longer ship, and the StatsD client used to send its
# metrics to Prometheus (profile observability).
FROM apache/superset:6.1.0

USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache \
        "psycopg2-binary==2.9.10" "statsd==4.0.1" \
    && /app/.venv/bin/python -c "import psycopg2, redis, statsd; print('drivers ok')"
USER superset
