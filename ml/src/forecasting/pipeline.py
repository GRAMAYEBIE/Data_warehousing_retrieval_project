"""One forecasting run, without input or output: backtest, choose, forecast.

The same run serves both targets (data.TARGETS): recorded trips and revenue (USD) per
pickup zone and hour. Two methods compete every month:
- the seasonal naive baseline: mean trips of the zone at that hour on that weekday over
  the last 4 weeks (public holidays left out), with an 80 % interval taken from its own
  past errors, by level of the forecast (baseline_bands);
- the challenger: LightGBM (model.py), with quantile models for its interval.

1. Rolling backtests: for each of the last three months (March, April, May with the data
   of 2026-11), both methods forecast the month from the weeks before it, the model being
   trained on the earlier months only. Nothing of the month forecast, or later, is used.
2. Choice (champion): the model is promoted only if it beats the baseline in most of the
   backtest months, on average, and on average on the high-demand zones (92 % of trips).
   Otherwise the baseline is the champion and the model stays the challenger, tracked in
   MLflow until it wins. Observed on the real data: the baseline won March and April, the
   model May only, so the baseline is in service.
3. Evaluation: the champion is scored on the last month (evaluate.report), its interval
   built from the earlier backtests only, so the coverage shown is an honest one.
4. Forecast: the champion forecasts the next month; history of six months or more needed.
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
BACKTESTS = 3
TIER_NAMES = np.array([name for name, _ in TIERS])
# Levels of the baseline forecast, for its interval: the spread of the errors grows with
# the level (counts), so the residuals are scaled by sqrt(level + 1) within each band.
LEVELS = [-np.inf, 1e-9, 0.5, 1, 2, 5, 10, 20, 50, 100, np.inf]


@dataclass
class Backtest:
    month: str
    rounds: int
    frame: pd.DataFrame  # zone-hour rows: grid, actual, baseline, model, model_lower, model_upper


@dataclass
class Result:
    target: str  # trips or revenue (data.TARGETS)
    train_months: list[str]
    validated_month: str
    forecast_month: str
    rounds: int
    champion: str  # "baseline" or "model"
    decision: str  # why, in one sentence
    backtests: pd.DataFrame  # month x method x segment scores (evaluate.report)
    evaluation: pd.DataFrame  # the champion on the last month, against the baseline
    beats_baseline: bool  # the model was promoted
    publishable: bool
    reasons: list[str]  # why it is not publishable, if so
    forecast: pd.DataFrame  # zone x day x hour of the next month
    daily: pd.DataFrame  # borough x day of the next month, with its own interval
    importance: pd.DataFrame
    final: Fitted  # the challenger trained on every month (logged in MLflow)


def _grid(history: History, x: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "zone_sk": history.zone_sk[x["zone"]],
            "zone_name": history.zone_name[x["zone"]],
            "borough": history.borough[x["zone"]],
            "tier": TIER_NAMES[x["tier"]],
            "date_day": days[x["day_index"]].date,
            "pickup_hour": x["hour"].to_numpy(),
            "baseline": x["naive_4w"].to_numpy(),
        }
    )


def backtest(history: History, start: pd.Timestamp, prior: list[pd.Timestamp]) -> Backtest:
    """Both methods forecast the month `start`, the model trained on `prior` months only."""
    fitted = fit(history, prior)
    days = month_days(start)
    x = build(history, start, days)
    pred = predict(fitted, x)
    frame = _grid(history, x, days)
    frame["model"] = pred["predicted"].to_numpy()
    frame["model_lower"] = pred["lower"].to_numpy()
    frame["model_upper"] = pred["upper"].to_numpy()
    frame["actual"] = actuals(history, days)
    return Backtest(start.strftime("%Y-%m"), fitted.rounds, frame)


def baseline_bands(frames: list[pd.DataFrame], unit: float = 1.0) -> pd.DataFrame:
    """10th and 90th percentiles of the scaled baseline error per level band; values are
    first expressed in trips (divided by the target's scale, `unit`)."""
    data = pd.concat(frames, ignore_index=True)
    base, actual = data["baseline"] / unit, data["actual"] / unit
    level = pd.cut(base, LEVELS, labels=False)
    scaled = (actual - base) / np.sqrt(base + 1)
    return scaled.groupby(level).quantile([0.1, 0.9]).unstack()


def baseline_interval(
    baseline: np.ndarray, bands: pd.DataFrame, unit: float = 1.0
) -> tuple[np.ndarray, np.ndarray]:
    base = baseline / unit
    level = pd.cut(pd.Series(base), LEVELS, labels=False)
    q = bands.reindex(level.to_numpy())
    spread = np.sqrt(base + 1)
    lower = np.clip(base + q[0.1].fillna(0).to_numpy() * spread, 0, None) * unit
    upper = (base + q[0.9].fillna(0).to_numpy() * spread) * unit
    return np.minimum(lower, baseline), np.maximum(upper, baseline)


def _as(frame: pd.DataFrame, method: str, bands: pd.DataFrame | None, unit: float = 1.0):
    """The frame with predicted / lower / upper of one method (for evaluate.report)."""
    out = frame.copy()
    if method == "model":
        out["predicted"], out["lower"], out["upper"] = (
            out["model"], out["model_lower"], out["model_upper"]
        )  # fmt: skip
    else:
        out["predicted"] = out["baseline"]
        if bands is None:
            out["lower"] = out["upper"] = np.nan
        else:
            out["lower"], out["upper"] = baseline_interval(out["baseline"].to_numpy(), bands, unit)
    return out


def choose(scores: pd.DataFrame) -> tuple[str, str]:
    """scores: one row per backtest month with overall and high-tier WMAPE of both methods."""
    wins = int((scores["model_wmape"] < scores["baseline_wmape"]).sum())
    needed = len(scores) // 2 + 1
    mean = scores.mean(numeric_only=True)
    promoted = (
        wins >= needed
        and mean.model_wmape < mean.baseline_wmape
        and mean.model_high <= mean.baseline_high
    )
    detail = (
        f"the model beat the baseline in {wins} of {len(scores)} backtest months "
        f"(mean error {mean.model_wmape:.1%} vs {mean.baseline_wmape:.1%}; high-demand zones "
        f"{mean.model_high:.1%} vs {mean.baseline_high:.1%})"
    )
    if promoted:
        return "model", f"model promoted: {detail}"
    return "baseline", f"baseline kept in service: {detail}"


def run(history: History) -> Result:
    starts = origins(history)
    tested = list(range(2, len(starts)))[-BACKTESTS:]  # at least two months to train on
    if not tested:
        raise ValueError("at least four months of history are needed to backtest a forecast")
    runs = [backtest(history, starts[i], starts[:i]) for i in tested]

    unit = history.scale
    rows, reports = [], []
    for k, bt in enumerate(runs):
        bands = baseline_bands([r.frame for r in runs[:k]], unit) if k else None
        for method in ("model", "baseline"):
            report = evaluate.report(_as(bt.frame, method, bands, unit))
            reports.append(report.assign(month=bt.month, method=method))
        seg = reports[-2].set_index(["segment_type", "segment"])  # the model's report
        high = seg.loc[("tier", "high")] if ("tier", "high") in seg.index else None
        rows.append(
            {
                "month": bt.month,
                "model_wmape": seg.loc[("overall", "all"), "wmape"],
                "baseline_wmape": seg.loc[("overall", "all"), "baseline_wmape"],
                "model_high": 0.0 if high is None else high["wmape"],
                "baseline_high": 0.0 if high is None else high["baseline_wmape"],
            }
        )
    champion, decision = choose(pd.DataFrame(rows))

    last = runs[-1]
    earlier = baseline_bands([r.frame for r in runs[:-1]], unit) if len(runs) > 1 else None
    validated = _as(last.frame, champion, earlier, unit)
    evaluation = evaluate.report(validated)

    reasons = []
    if len(history.months) < MIN_MONTHS:
        reasons.append(f"{len(history.months)} months of history, {MIN_MONTHS} required")

    # The challenger on every month, logged in MLflow whatever the decision.
    final = fit_rounds(*stack(history, starts), last.rounds)
    origin = history.days[-1] + pd.Timedelta(days=1)
    next_days = month_days(origin)
    xf = build(history, origin, next_days)
    grid = _grid(history, xf, next_days)
    if champion == "model":
        pred = predict(final, xf)
        grid["predicted"], grid["lower"], grid["upper"] = (
            pred["predicted"].to_numpy(), pred["lower"].to_numpy(), pred["upper"].to_numpy()
        )  # fmt: skip
    else:
        grid["predicted"] = grid["baseline"]
        all_bands = baseline_bands([r.frame for r in runs], unit)
        grid["lower"], grid["upper"] = baseline_interval(
            grid["baseline"].to_numpy(), all_bands, unit
        )
    grid["method"] = champion
    grid["low_confidence"] = grid["tier"] == "sparse"
    forecast = grid.drop(columns="baseline")

    # Borough-day interval from the champion's borough-day errors over every backtest.
    history_frames = [_as(r.frame, champion, None) for r in runs]
    bands = evaluate.daily_interval(pd.concat(history_frames, ignore_index=True))
    daily = forecast.groupby(["borough", "date_day"], as_index=False)["predicted"].sum()
    low = daily["borough"].map(lambda b: bands.get(b, (1.0, 1.0))[0])
    high = daily["borough"].map(lambda b: bands.get(b, (1.0, 1.0))[1])
    daily["lower"] = np.minimum(daily["predicted"] * low, daily["predicted"])
    daily["upper"] = np.maximum(daily["predicted"] * high, daily["predicted"])

    return Result(
        target=history.target,
        train_months=[s.strftime("%Y-%m") for s in starts],
        validated_month=last.month,
        forecast_month=origin.strftime("%Y-%m"),
        rounds=last.rounds,
        champion=champion,
        decision=decision,
        backtests=pd.concat(reports, ignore_index=True),
        evaluation=evaluation,
        beats_baseline=champion == "model",
        publishable=not reasons,
        reasons=reasons,
        forecast=forecast,
        daily=daily,
        importance=importance(final),
        final=final,
    )
