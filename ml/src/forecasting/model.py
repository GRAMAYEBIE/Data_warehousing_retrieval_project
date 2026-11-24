"""LightGBM models of trips per zone-hour: the expected value and an 80 % interval.

- Expected trips: Poisson objective (counts, many zeros, variance growing with the level).
- Interval: two quantile models (10th and 90th percentiles) on the same features.
- Training rows: one block per past month, each built from its own origin, so the model
  learns how a month turns out compared with the weeks before it.
- Number of trees: early stopping on the last training month, then a refit on all of them.
"""

from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from forecasting.data import History
from forecasting.features import CATEGORICAL, FEATURES, actuals, build, month_days, origin_index

PARAMS = {
    "objective": "poisson",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "seed": 7,
    "deterministic": True,
    "num_threads": 4,
    "verbose": -1,
}
QUANTILES = {"lower": 0.1, "upper": 0.9}
MAX_ROUNDS = 2000
DEFAULT_ROUNDS = 400


@dataclass
class Fitted:
    mean: lgb.Booster
    lower: lgb.Booster
    upper: lgb.Booster
    rounds: int


def origins(history: History) -> list[pd.Timestamp]:
    """First day of every month of the history that has 4 weeks of history before it."""
    starts = [d for d in history.days if d.day == 1]
    return [d for d in starts if origin_index(history, d) >= 28]


def stack(history: History, starts: list[pd.Timestamp]) -> tuple[pd.DataFrame, np.ndarray]:
    frames, targets = [], []
    for start in starts:
        days = month_days(start)
        frames.append(build(history, start, days))
        targets.append(actuals(history, days))
    return pd.concat(frames, ignore_index=True), np.concatenate(targets)


def _dataset(x: pd.DataFrame, y: np.ndarray) -> lgb.Dataset:
    return lgb.Dataset(x[FEATURES], y, categorical_feature=CATEGORICAL, free_raw_data=False)


def fit_rounds(x: pd.DataFrame, y: np.ndarray, rounds: int) -> Fitted:
    data = _dataset(x, y)
    mean = lgb.train(PARAMS, data, rounds)
    bounds = {
        name: lgb.train({**PARAMS, "objective": "quantile", "alpha": alpha}, data, rounds)
        for name, alpha in QUANTILES.items()
    }
    return Fitted(mean, bounds["lower"], bounds["upper"], rounds)


def fit(history: History, starts: list[pd.Timestamp]) -> Fitted:
    """Early stopping on the last month of `starts`, then refit on all of them."""
    rounds = DEFAULT_ROUNDS
    if len(starts) >= 2:
        x1, y1 = stack(history, starts[:-1])
        x2, y2 = stack(history, starts[-1:])
        probe = lgb.train(
            PARAMS,
            _dataset(x1, y1),
            MAX_ROUNDS,
            valid_sets=[_dataset(x2, y2)],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )
        # One more month of rows in the refit: a few more trees than the probe needed.
        rounds = max(50, int(round(probe.best_iteration * 1.1)))
    x, y = stack(history, starts)
    return fit_rounds(x, y, rounds)


def predict(fitted: Fitted, x: pd.DataFrame) -> pd.DataFrame:
    """Expected trips and the interval, never negative and always around the expected value."""
    mean = np.clip(fitted.mean.predict(x[FEATURES]), 0, None)
    lower = np.clip(fitted.lower.predict(x[FEATURES]), 0, None)
    upper = np.clip(fitted.upper.predict(x[FEATURES]), 0, None)
    return pd.DataFrame(
        {"predicted": mean, "lower": np.minimum(lower, mean), "upper": np.maximum(upper, mean)}
    )


def importance(fitted: Fitted) -> pd.DataFrame:
    gain = fitted.mean.feature_importance(importance_type="gain")
    frame = pd.DataFrame({"feature": fitted.mean.feature_name(), "gain": gain})
    frame["share"] = frame["gain"] / frame["gain"].sum()
    return frame.sort_values("gain", ascending=False, ignore_index=True)
