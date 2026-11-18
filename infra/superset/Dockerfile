# Superset image of the platform: the official 6.1.0 image plus the PostgreSQL driver,
# which recent official images no longer ship.
FROM apache/superset:6.1.0

USER root
RUN uv pip install --python /app/.venv/bin/python --no-cache \
        "psycopg2-binary==2.9.10" \
    && /app/.venv/bin/python -c "import psycopg2, redis; print('drivers ok')"
USER superset
