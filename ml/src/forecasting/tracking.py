"""MLflow: every run is recorded with what is needed to trace a forecast back to its data,
code and settings (experiment "demand_forecast"):

- tags: the data publication, months, decision and the reasons when not publishable, and
  a fingerprint of the code;
- parameters: model settings, number of trees, features;
- metrics: the validation scores of the model and the baseline per segment;
- artefacts: the evaluation table, the feature importance, the model itself;
- registry: a publishable run's model becomes a version of "demand_forecast", aliased
  "production", so the model behind the forecast in use is one lookup away.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import mlflow
import mlflow.lightgbm
from mlflow import MlflowClient

from forecasting.features import FEATURES
from forecasting.model import PARAMS, QUANTILES
from forecasting.pipeline import Result

EXPERIMENT = "demand_forecast"
MODEL_NAME = "demand_forecast"
METRICS = ("mae", "wmape", "bias", "baseline_mae", "baseline_wmape", "coverage_80")


def code_fingerprint() -> str:
    """SHA-256 of the forecasting package's source files: the exact code of a run, also in
    an image without git (the image is built from the repository at one commit)."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _key(*parts: str) -> str:
    return re.sub(r"[^\w\-. /]", "_", ".".join(parts)).lower()


def log(result: Result, data_run: str, history_months: list[str], tracking_uri: str) -> str:
    """Record the run in MLflow; returns its run id (also the key of ml.forecast_run)."""
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT)
    with mlflow.start_run(run_name=f"forecast {result.forecast_month}") as run:
        mlflow.set_tags(
            {
                "data_run": data_run,
                "history_months": ",".join(history_months),
                "validated_month": result.validated_month,
                "forecast_month": result.forecast_month,
                "beats_baseline": str(result.beats_baseline).lower(),
                "publishable": str(result.publishable).lower(),
                "reasons": " | ".join(result.reasons) or "-",
                "target": "recorded valid trips per pickup zone and hour",
                "code_sha256": code_fingerprint(),
            }
        )
        mlflow.log_params(
            {
                **{f"lgbm.{k}": v for k, v in PARAMS.items()},
                "rounds": result.rounds,
                "quantiles": ",".join(f"{k}={v}" for k, v in QUANTILES.items()),
                "features": ",".join(FEATURES),
                "train_origins": ",".join(result.train_months),
                "split": "time-based: train on earlier months, validate on the last one",
            }
        )
        metrics = {}
        for row in result.evaluation.to_dict("records"):
            for name in METRICS:
                value = row.get(name)
                if value is not None and value == value:  # not NaN
                    metrics[_key(row["segment_type"], row["segment"], name)] = float(value)
        mlflow.log_metrics(metrics)
        mlflow.log_text(result.evaluation.to_csv(index=False), "evaluation.csv")
        mlflow.log_text(result.importance.to_csv(index=False), "feature_importance.csv")
        info = mlflow.lightgbm.log_model(
            result.final.mean,
            name="model",
            registered_model_name=MODEL_NAME if result.publishable else None,
        )
        if result.publishable and info.registered_model_version is not None:
            MlflowClient().set_registered_model_alias(
                MODEL_NAME, "production", info.registered_model_version
            )
        return run.info.run_id
