"""One forecasting run, without input or output: backtest, choose, forecast.

The same run serves both targets (data.TARGETS): recorded trips and revenue (USD) per
pickup zone and hour. Three methods compete every month:
- the seasonal naive baseline: mean trips of the zone at that hour on that weekday over
  the last 4 weeks (public holidays left out), with an 80 % interval taken from its own
  errors over up to six past months, by level of the forecast (baseline_bands);
- the adjusted baseline: the same, corrected per borough by the recent two-week trend and
  the month's usual change from last year (features.adjustment);
- LightGBM (model.py), with quantile models for its interval; it learns from the gap
  between forecast and actual by construction (retrained on every past month's errors),
  and last month's forecast error and the same month a year earlier are among its
  features.
Every month the models are retrained on all published months: the platform keeps learning
as months arrive, and MLflow records each version with its errors.

1. Rolling backtests: for each of the last three months (March, April, May with the data
   of 2026-11), both methods forecast the month from the weeks before it, the model being
   trained on the earlier months only. Nothing of the month forecast, or later, is used.
2. Choice (champion): a challenger replaces the baseline only if it beats it in most of
   the backtest months, on average, and on average on the high-demand zones (92 % of
   trips); among those that qualify, the lowest mean error wins. Otherwise the baseline
   stays the champion and the others remain challengers, tracked in MLflow until they win.
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
from forecasting.model import (
    HALF_LIFE,
    Fitted,
    fit,
    fit_rounds,
    importance,
    origins,
    predict,
    stack,
)

MIN_MONTHS = 6
BACKTESTS = 3
# The two baselines need no training: their intervals are calibrated on the errors of up
# to six past months (more real gaps than the three model backtests give).
CALIBRATION_MONTHS = 6
METHODS = ("baseline", "adjusted", "model")  # the incumbent first
METHOD_NAMES = {
    "baseline": "seasonal baseline",
    "adjusted": "adjusted baseline",
    "model": "LightGBM model",
}
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
    half_life: float = HALF_LIFE  # months; recency of LightGBM's training weights


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
            "adjusted": (x["naive_4w"] * x["adj_factor"]).to_numpy(),
        }
    )


def naive_frame(history: History, start: pd.Timestamp) -> pd.DataFrame:
    """Both baselines and the recorded values for the month `start` (no model): used to
    calibrate the baselines' intervals on more past months at little cost."""
    days = month_days(start)
    frame = _grid(history, build(history, start, days), days)
    frame["actual"] = actuals(history, days)
    return frame


def backtest(
    history: History,
    start: pd.Timestamp,
    prior: list[pd.Timestamp],
    half_life: float = HALF_LIFE,
) -> Backtest:
    """Both methods forecast the month `start`, the model trained on `prior` months only."""
    fitted = fit(history, prior, half_life)
    days = month_days(start)
    x = build(history, start, days)
    pred = predict(fitted, x)
    frame = _grid(history, x, days)
    frame["model"] = pred["predicted"].to_numpy()
    frame["model_lower"] = pred["lower"].to_numpy()
    frame["model_upper"] = pred["upper"].to_numpy()
    frame["actual"] = actuals(history, days)
    return Backtest(start.strftime("%Y-%m"), fitted.rounds, frame)


def baseline_bands(
    frames: list[pd.DataFrame], unit: float = 1.0, column: str = "baseline"
) -> pd.DataFrame:
    """10th and 90th percentiles of the scaled error of a baseline (`column`) per level
    band; values are first expressed in trips (divided by the target's scale, `unit`)."""
    data = pd.concat(frames, ignore_index=True)
    base, actual = data[column] / unit, data["actual"] / unit
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
    else:  # baseline or adjusted: intervals from their own past errors
        out["predicted"] = out[method]
        if bands is None:
            out["lower"] = out["upper"] = np.nan
        else:
            out["lower"], out["upper"] = baseline_interval(out[method].to_numpy(), bands, unit)
    return out


def choose(scores: pd.DataFrame) -> tuple[str, str]:
    """scores: one row per backtest month with `<method>_wmape` (overall) and `<method>_high`
    (high-demand zones) for the baseline and each challenger present.

    A challenger replaces the baseline only if it beats it in most months, on average and on
    the busiest zones; among those that qualify, the lowest mean error wins."""
    mean = scores.mean(numeric_only=True)
    needed = len(scores) // 2 + 1
    challengers = [m for m in METHODS[1:] if f"{m}_wmape" in scores]
    qualified, details = [], []
    for m in challengers:
        wins = int((scores[f"{m}_wmape"] < scores["baseline_wmape"]).sum())
        details.append(
            f"the {METHOD_NAMES[m]} beat the baseline in {wins} of {len(scores)} backtest "
            f"months (mean error {mean[f'{m}_wmape']:.1%} vs {mean.baseline_wmape:.1%}; "
            f"high-demand zones {mean[f'{m}_high']:.1%} vs {mean.baseline_high:.1%})"
        )
        if (
            wins >= needed
            and mean[f"{m}_wmape"] < mean.baseline_wmape
            and mean[f"{m}_high"] <= mean.baseline_high
        ):
            qualified.append(m)
    detail = "; ".join(details)
    if qualified:
        best = min(qualified, key=lambda m: mean[f"{m}_wmape"])
        return best, f"{METHOD_NAMES[best]} promoted: {detail}"
    return "baseline", f"baseline kept in service: {detail}"


def run(history: History, half_life: float = HALF_LIFE) -> Result:
    """`half_life`: memory of LightGBM's training weights (shorter after a drift)."""
    starts = origins(history)
    tested = list(range(2, len(starts)))[-BACKTESTS:]  # at least two months to train on
    if not tested:
        raise ValueError("at least four months of history are needed to backtest a forecast")
    runs = [backtest(history, starts[i], starts[:i], half_life) for i in tested]

    unit = history.scale
    # Both baselines on every past month (no training): the real errors their intervals are
    # calibrated on, always from months before the one evaluated or forecast.
    naive = {s: naive_frame(history, s) for s in starts}

    def bands_before(start: pd.Timestamp) -> dict[str, pd.DataFrame | None]:
        frames = [naive[s] for s in starts if s < start][-CALIBRATION_MONTHS:]
        return {
            m: baseline_bands(frames, unit, column=m) if frames else None
            for m in ("baseline", "adjusted")
        }

    rows, reports = [], []
    for bt in runs:
        bands = bands_before(pd.Timestamp(f"{bt.month}-01"))
        row = {"month": bt.month}
        for method in METHODS:
            report = evaluate.report(_as(bt.frame, method, bands.get(method), unit))
            reports.append(report.assign(month=bt.month, method=method))
            seg = report.set_index(["segment_type", "segment"])
            high = seg.loc[("tier", "high")] if ("tier", "high") in seg.index else None
            row[f"{method}_wmape"] = seg.loc[("overall", "all"), "wmape"]
            row[f"{method}_high"] = 0.0 if high is None else high["wmape"]
        rows.append(row)
    champion, decision = choose(pd.DataFrame(rows))

    last = runs[-1]
    last_bands = bands_before(pd.Timestamp(f"{last.month}-01"))
    validated = _as(last.frame, champion, last_bands.get(champion), unit)
    evaluation = evaluate.report(validated)

    reasons = []
    if len(history.months) < MIN_MONTHS:
        reasons.append(f"{len(history.months)} months of history, {MIN_MONTHS} required")

    # The challenger on every month, logged in MLflow whatever the decision.
    final = fit_rounds(*stack(history, starts), last.rounds, half_life)
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
        grid["predicted"] = grid[champion]
        grid["lower"], grid["upper"] = baseline_interval(
            grid[champion].to_numpy(), bands_before(origin)[champion], unit
        )
    grid["method"] = champion
    grid["low_confidence"] = grid["tier"] == "sparse"
    forecast = grid.drop(columns=["baseline", "adjusted"])

    # Borough-day interval from the champion's borough-day errors: the model's backtests, or
    # for a baseline its errors over up to six past months (one month alone gave a range too
    # narrow: 43 % of the days of April 2025 fell inside it).
    if champion == "model":
        history_frames = [_as(r.frame, champion, None) for r in runs]
    else:
        history_frames = [_as(naive[s], champion, None) for s in starts[-CALIBRATION_MONTHS:]]
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
        beats_baseline=champion != "baseline",
        publishable=not reasons,
        reasons=reasons,
        forecast=forecast,
        daily=daily,
        importance=importance(final),
        final=final,
        half_life=half_life,
    )
