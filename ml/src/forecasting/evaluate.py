"""Error measures that respect the imbalance of the data.

MAPE is undefined on the many zero-trip hours, and one overall figure is dominated by the
47 busy Manhattan and airport zones, so the forecast is judged with:

- MAE (trips per zone-hour) and WMAPE = sum |error| / sum actual (defined with zeros,
  weighted by volume), overall and per borough and per demand tier;
- the same at the borough x day level, the grain a planner reads;
- bias = sum error / sum actual (a forecast that is always low is not acceptable even if
  its WMAPE looks fine);
- coverage of the 80 % interval: the share of actual values inside [p10, p90].
Each is reported for the model and for the seasonal naive baseline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wmape(actual: np.ndarray, predicted: np.ndarray) -> float:
    total = float(np.sum(actual))
    return float(np.sum(np.abs(predicted - actual)) / total) if total > 0 else float("nan")


def scores(actual, model, baseline, lower=None, upper=None) -> dict:
    actual, model, baseline = map(np.asarray, (actual, model, baseline))
    total = float(actual.sum())
    out = {
        "rows": int(actual.size),
        "actual_trips": total,
        "mae": float(np.mean(np.abs(model - actual))),
        "wmape": wmape(actual, model),
        "bias": float((model.sum() - total) / total) if total > 0 else float("nan"),
        "baseline_mae": float(np.mean(np.abs(baseline - actual))),
        "baseline_wmape": wmape(actual, baseline),
    }
    if lower is not None and upper is not None:
        inside = (actual >= np.asarray(lower)) & (actual <= np.asarray(upper))
        out["coverage_80"] = float(np.mean(inside))
    return out


def report(frame: pd.DataFrame) -> pd.DataFrame:
    """frame: one row per zone-hour with borough, tier, date_day, actual, predicted, baseline,
    lower, upper. Returns one row per segment (overall, borough, tier, borough-day)."""
    rows = [{"segment_type": "overall", "segment": "all", **_scores(frame)}]
    for kind in ("borough", "tier"):
        for name, part in frame.groupby(kind, sort=True):
            rows.append({"segment_type": kind, "segment": str(name), **_scores(part)})
    daily = frame.groupby(["borough", "date_day"], as_index=False)[
        ["actual", "predicted", "baseline"]
    ].sum()
    rows.append({"segment_type": "borough_day", "segment": "all", **_scores(daily, interval=False)})
    for name, part in daily.groupby("borough", sort=True):
        rows.append(
            {"segment_type": "borough_day", "segment": str(name), **_scores(part, interval=False)}
        )
    return pd.DataFrame(rows)


def _scores(part: pd.DataFrame, interval: bool = True) -> dict:
    return scores(
        part["actual"],
        part["predicted"],
        part["baseline"],
        part["lower"] if interval else None,
        part["upper"] if interval else None,
    )


def daily_interval(frame: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Per borough, the 10th and 90th percentiles of actual / predicted at the borough-day
    level on the validation month. The zone-hour quantiles cannot simply be added up (that
    interval would be far too wide), so a borough-day forecast gets this empirical one."""
    daily = frame.groupby(["borough", "date_day"])[["actual", "predicted"]].sum()
    daily = daily[daily["predicted"] > 0]
    ratio = daily["actual"] / daily["predicted"]
    out = {}
    for borough, values in ratio.groupby(level="borough"):
        out[str(borough)] = (float(values.quantile(0.1)), float(values.quantile(0.9)))
    return out
