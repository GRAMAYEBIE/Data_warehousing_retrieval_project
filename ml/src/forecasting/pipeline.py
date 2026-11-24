"""One forecasting run, without input or output: validate, decide, forecast.

1. Validation: train on every month but the last, forecast the last month from the weeks
   before it, and score the model against the seasonal naive baseline (evaluate.py).
2. Decision: the forecast is publishable only if the model beats the baseline overall
   and on the high-demand zones (92 % of trips), and the history has six months or more.
3. Forecast: refit on every month (same number of trees) and forecast the next month.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from forecasting import evaluate
from forecasting.data import History
from forecasting.features import TIERS, actuals, build, month_days
from forecasting.model import Fitted, fit, fit_rounds, importance, origins, predict, stack

MIN_MONTHS = 6
TIER_NAMES = np.array([name for name, _ in TIERS])


@dataclass
class Result:
    train_months: list[str]
    validated_month: str
    forecast_month: str
    rounds: int
    evaluation: pd.DataFrame  # evaluate.report on the validation month
    beats_baseline: bool
    publishable: bool
    reasons: list[str]  # why it is not publishable, if so
    forecast: pd.DataFrame  # zone x day x hour of the next month
    daily: pd.DataFrame  # borough x day of the next month, with its own interval
    importance: pd.DataFrame
    final: Fitted


def _frame(history: History, x: pd.DataFrame, days: pd.DatetimeIndex, pred: pd.DataFrame):
    return pd.DataFrame(
        {
            "zone_sk": history.zone_sk[x["zone"]],
            "zone_name": history.zone_name[x["zone"]],
            "borough": history.borough[x["zone"]],
            "tier": TIER_NAMES[x["tier"]],
            "date_day": days[x["day_index"]].date,
            "pickup_hour": x["hour"].to_numpy(),
            "baseline": x["naive_4w"].to_numpy(),
            "predicted": pred["predicted"].to_numpy(),
            "lower": pred["lower"].to_numpy(),
            "upper": pred["upper"].to_numpy(),
        }
    )


def run(history: History) -> Result:
    starts = origins(history)
    if len(starts) < 2:
        raise ValueError("at least three months of history are needed to validate a forecast")
    validation, training = starts[-1], starts[:-1]

    fitted = fit(history, training)
    days = month_days(validation)
    x = build(history, validation, days)
    frame = _frame(history, x, days, predict(fitted, x))
    frame["actual"] = actuals(history, days)
    evaluation = evaluate.report(frame)

    def row(kind: str, name: str) -> pd.Series:
        match = evaluation[(evaluation.segment_type == kind) & (evaluation.segment == name)]
        return match.iloc[0] if len(match) else pd.Series({"wmape": 0.0, "baseline_wmape": 0.0})

    overall, high = row("overall", "all"), row("tier", "high")
    beats = bool(overall.wmape < overall.baseline_wmape and high.wmape <= high.baseline_wmape)
    reasons = []
    if not beats:
        reasons.append(
            f"the model does not beat the seasonal naive baseline (WMAPE {overall.wmape:.3f} "
            f"vs {overall.baseline_wmape:.3f} overall, {high.wmape:.3f} vs "
            f"{high.baseline_wmape:.3f} on high-demand zones)"
        )
    if len(history.months) < MIN_MONTHS:
        reasons.append(f"{len(history.months)} months of history, {MIN_MONTHS} required")

    final = fit_rounds(*stack(history, starts), fitted.rounds)
    origin = history.days[-1] + pd.Timedelta(days=1)
    next_days = month_days(origin)
    xf = build(history, origin, next_days)
    forecast = _frame(history, xf, next_days, predict(final, xf)).drop(columns="baseline")
    forecast["low_confidence"] = forecast["tier"] == "sparse"

    bands = evaluate.daily_interval(frame)
    daily = forecast.groupby(["borough", "date_day"], as_index=False)["predicted"].sum()
    low = daily["borough"].map(lambda b: bands.get(b, (1.0, 1.0))[0])
    high = daily["borough"].map(lambda b: bands.get(b, (1.0, 1.0))[1])
    daily["lower"] = np.minimum(daily["predicted"] * low, daily["predicted"])
    daily["upper"] = np.maximum(daily["predicted"] * high, daily["predicted"])

    return Result(
        train_months=[d.strftime("%Y-%m") for d in training],
        validated_month=validation.strftime("%Y-%m"),
        forecast_month=origin.strftime("%Y-%m"),
        rounds=fitted.rounds,
        evaluation=evaluation,
        beats_baseline=beats,
        publishable=not reasons,
        reasons=reasons,
        forecast=forecast,
        daily=daily,
        importance=importance(final),
        final=final,
    )
