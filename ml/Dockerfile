# Forecasting job (profile ml): trains, evaluates and publishes the demand forecast.
# Run by Airflow after each publication, or by hand: docker compose run --rm --no-deps forecast
FROM python:3.12-slim

# No git in the image: MLflow records a fingerprint of the code instead (tracking.py).
ENV GIT_PYTHON_REFRESH=quiet \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=10

# LightGBM uses OpenMP.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
RUN pip install --no-deps .

ENTRYPOINT ["python", "-m", "forecasting"]
