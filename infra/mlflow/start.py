"""Start the MLflow server once its artefact bucket exists (created on first start)."""

import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

bucket = os.environ.get("MLFLOW_BUCKET", "mlflow")
s3 = boto3.client(
    "s3",
    endpoint_url=os.environ["MLFLOW_S3_ENDPOINT_URL"],
    config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
)
try:
    s3.head_bucket(Bucket=bucket)
except ClientError:
    s3.create_bucket(Bucket=bucket)
    print(f"created bucket {bucket}", flush=True)

store = (
    f"postgresql+psycopg2://mlflow:{os.environ['MLFLOW_DB_PASSWORD']}"
    f"@{os.environ.get('MLFLOW_DB_HOST', 'postgres')}:5432/mlflow_meta"
)
os.execvp(
    "mlflow",
    [
        "mlflow",
        "server",
        "--host", "0.0.0.0",
        "--port", "5000",
        "--workers", "1",
        "--backend-store-uri", store,
        "--artifacts-destination", f"s3://{bucket}",
        "--serve-artifacts",
        # Requests come from the training job (mlflow:5000) and through the SSH tunnel.
        "--allowed-hosts", "mlflow,mlflow:5000,localhost,localhost:*,127.0.0.1,127.0.0.1:*",
    ],
)
