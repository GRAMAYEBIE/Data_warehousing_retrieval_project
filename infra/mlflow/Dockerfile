# MLflow tracking server (profile ml): runs, parameters and metrics in PostgreSQL
# (database mlflow_meta), model files in the object store (bucket MLFLOW_BUCKET on RustFS),
# served through the server itself, so a training job needs no storage credentials.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PYTHONUNBUFFERED=1

RUN pip install "mlflow==3.17.2" "psycopg2-binary==2.9.10" "boto3==1.44.3"

# RustFS, like MinIO, is addressed by path (http://rustfs:9000/bucket/key).
RUN mkdir -p /root/.aws && printf '[default]\ns3 =\n    addressing_style = path\n' > /root/.aws/config

COPY start.py /start.py
EXPOSE 5000
CMD ["python", "/start.py"]
