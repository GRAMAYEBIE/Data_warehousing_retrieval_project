"""MLflow: every run is recorded with what is needed to trace a forecast back to its data,
code and settings (experiments "demand_forecast" for trips, "revenue_forecast" for USD):

- tags: the data publication, months, decision and the reasons when not publishable, and
  a fingerprint of the code;
- parameters: model settings, number of trees, features;
- metrics: the validation scores of the model and the baseline per segment;
- artefacts: the evaluation table, the feature importance, the model itself;
- registry: every run's model is a version of "demand_forecast" with the alias
  "challenger"; it gets "production" only while it is the champion in service.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path

import mlflow
import mlflow.lightgbm
from mlflow import MlflowClient

from forecasting.features import FEATURES
from forecasting.model import PARAMS, QUANTILES
from forecasting.pipeline import Result

# Experiment and registered model per target (data.TARGETS).
NAMES = {"trips": "demand_forecast", "revenue": "revenue_forecast"}
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


def log(
    result: Result,
    data_run: str,
    history_months: list[str],
    tracking_uri: str,
    replay: bool = False,
) -> str:
    """Record the run in MLflow; returns its run id (also the key of ml.forecast_run). A
    replay (forecast made again as at the time, for the check history) is tagged and its
    model is not registered."""
    name = NAMES[result.target]
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(name)
    prefix = "replay " if replay else ""
    with mlflow.start_run(run_name=f"{prefix}{result.target} {result.forecast_month}") as run:
        mlflow.set_tags(
            {
                "replay": str(replay).lower(),
                "target": result.target,
                "data_run": data_run,
                "history_months": ",".join(history_months),
                "validated_month": result.validated_month,
                "forecast_month": result.forecast_month,
                "champion": result.champion,
                "decision": result.decision,
                "beats_baseline": str(result.beats_baseline).lower(),
                "publishable": str(result.publishable).lower(),
                "reasons": " | ".join(result.reasons) or "-",
                "definition": f"{result.target} of recorded valid trips per pickup zone and hour",
                "code_sha256": code_fingerprint(),
            }
        )
        mlflow.log_params(
            {
                **{f"lgbm.{k}": v for k, v in PARAMS.items()},
                "rounds": result.rounds,
                "half_life_months": result.half_life,  # recency of training weights
                "quantiles": ",".join(f"{k}={v}" for k, v in QUANTILES.items()),
                "features": ",".join(FEATURES),
                "train_origins": ",".join(result.train_months),
                "split": "rolling backtests: each month forecast from the months before it",
            }
        )
        metrics = {}
        for row in result.evaluation.to_dict("records"):
            for metric in METRICS:
                value = row.get(metric)
                if value is not None and value == value:  # not NaN
                    metrics[_key(row["segment_type"], row["segment"], metric)] = float(value)
        for row in result.backtests.to_dict("records"):
            if row["segment_type"] in ("overall", "borough_day") and row["segment"] == "all":
                key = _key("backtest", row["month"], row["method"], row["segment_type"], "wmape")
                metrics[key] = float(row["wmape"])
        mlflow.log_metrics(metrics)
        mlflow.log_text(result.evaluation.to_csv(index=False), "evaluation.csv")
        mlflow.log_text(result.backtests.to_csv(index=False), "backtests.csv")
        mlflow.log_text(result.importance.to_csv(index=False), "feature_importance.csv")
        if replay:
            return run.info.run_id
        # The challenger is registered every month; it carries the alias "production" only
        # while it is the champion (otherwise the baseline is in service, not a model).
        info = mlflow.lightgbm.log_model(
            result.final.mean, name="model", registered_model_name=name
        )
        version = info.registered_model_version
        if version is not None:
            client = MlflowClient()
            client.set_registered_model_alias(name, "challenger", version)
            if result.champion == "model" and result.publishable:
                client.set_registered_model_alias(name, "production", version)
            elif result.publishable:
                with contextlib.suppress(Exception):  # no production alias to remove
                    client.delete_registered_model_alias(name, "production")
        return run.info.run_id
