"""Features of one forecast: a month ahead, from what was known the day before it started.

A forecast is made at an origin (the first day of the month to forecast) for every zone,
day and hour of that month. Every feature is computed from the days strictly before the
origin, so the model never sees the month it forecasts (tests/test_forecasting.py proves it
by changing that month and checking that no feature moves):

- the seasonal naive profile: mean trips of the zone at that hour on that weekday over the
  last 4 weeks (also the baseline the model must beat), and the same over 8 weeks;
- the zone's hourly profile and level over the last 4 weeks, and its trend (last 2 weeks
  against the 2 before; a 4-week trend was tried and made May worse, so it is not used);
- its demand tier, from its level over 8 weeks (high, medium, low, sparse);
- the calendar of the target hour: hour, weekday, weekend, public holiday, day of month,
  days ahead of the origin;
- what the forecast got wrong last month (learning from the gap): the seasonal baseline's
  forecast of the previous month against what was recorded, per zone and per borough. It
  is the quantity the monthly forecast-against-actual check measures (check.py), recomputed
  here for every origin so that backtests can use it too, and known at the origin;
- the same month a year earlier, once a year of history exists: the zone's weekday and
  hour profile in that month, and how much that month differed from the four weeks before
  it (the yearly seasonality, e.g. a summer slowdown). Missing before (NaN, which LightGBM
  handles).

Public holidays are left out of the profiles: a Christmas Day is not a typical Wednesday.

The adjusted baseline (`adj_factor`, not a model feature) corrects the seasonal baseline
per borough with the recent trend (last two weeks against the two before, half of it,
within ±10 %) and the month's usual change from last year (within -20 % and +25 %). It
competes with the plain baseline and the model (pipeline.py).

Measured on the published months (forecasting --compare-baselines and an experiment on
every month, error per borough and day): correcting the baseline by last month's error
made it worse (14.5 % against 12.9 %): most monthly errors come from seasonal changes (the
return to school in September, the holidays) that do not carry over to the next month, so
last month's error is kept as a model feature only, where LightGBM learns when it matters.
The two-week trend and last year's seasonality each improved the baseline (12.6 % and
12.5 %; January 2026 from 20.7 % to 16.0 % with last year's January).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from forecasting.data import History

# Mean trips per hour over the 8 weeks before the origin.
TIERS = (("high", 20.0), ("medium", 2.0), ("low", 0.2), ("sparse", 0.0))
TIER_CODE = {name: i for i, (name, _) in enumerate(TIERS)}

FEATURES = [
    "zone",
    "borough",
    "tier",
    "hour",
    "weekday",
    "is_weekend",
    "is_holiday",
    "day_of_month",
    "days_ahead",
    "naive_4w",
    "naive_8w",
    "zone_hour_4w",
    "level_4w",
    "trend_2w",
    "gap_last_zone",
    "gap_last_borough",
    "naive_ly",
    "ly_ratio",
]
CATEGORICAL = ["zone", "borough"]
# Adjusted baseline: share of the two-week trend applied, and the bounds of each factor.
TREND_DAMPING = 0.5
TREND_BOUNDS = (0.90, 1.10)
LY_BOUNDS = (0.80, 1.25)


def tier_of(level: np.ndarray) -> np.ndarray:
    out = np.full(level.shape, len(TIERS) - 1)
    for code, (_, floor) in reversed(list(enumerate(TIERS))):
        out[level >= floor] = code
    return out


def _weekday_profile(trips: np.ndarray, days: pd.DatetimeIndex, holidays: frozenset) -> np.ndarray:
    """Mean per zone, weekday (0 = Monday) and hour; a weekday absent from the window falls
    back to the mean of all its days."""
    usable = np.array([d not in holidays for d in days], dtype=bool)
    overall = trips[:, usable, :].mean(axis=1) if usable.any() else np.zeros(trips[:, 0, :].shape)
    out = np.empty((trips.shape[0], 7, 24))
    for k in range(7):
        sel = usable & (days.dayofweek == k)
        out[:, k, :] = trips[:, sel, :].mean(axis=1) if sel.any() else overall
    return out


def origin_index(history: History, origin: pd.Timestamp) -> int:
    """Number of history days before the origin (the origin may be after the last day)."""
    return int((history.days < origin).sum())


def _by_borough(values: np.ndarray, borough: np.ndarray) -> dict[str, float]:
    return {b: float(values[borough == b].sum()) for b in np.unique(borough)}


def last_month_gap(history: History, origin: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """(per zone, per zone's borough) relative error of the seasonal baseline's forecast of
    the month before the origin: (forecast - recorded) / recorded; negative means the
    forecast was too low. NaN when that month cannot be forecast from four weeks before it.
    Only days before the origin are read."""
    previous = (origin - pd.offsets.MonthBegin(1)).normalize()
    p = origin_index(history, previous)
    o = origin_index(history, origin)
    n = len(history.zone_sk)
    if p < 28 or o - p < 28:
        return np.full(n, np.nan), np.full(n, np.nan)
    profile = _weekday_profile(
        history.trips[:, p - 28 : p, :], history.days[p - 28 : p], history.holidays
    )
    days = history.days[p:o]
    forecast = profile[:, days.dayofweek.to_numpy(), :].sum(axis=(1, 2))
    recorded = history.trips[:, p:o, :].sum(axis=(1, 2))
    zone = (forecast - recorded) / (recorded + 24.0 * history.scale)  # small zones stay finite
    f, r = _by_borough(forecast, history.borough), _by_borough(recorded, history.borough)
    borough = np.array([(f[b] - r[b]) / r[b] if r[b] > 0 else np.nan for b in history.borough])
    return zone, borough


def last_year(
    history: History, origin: pd.Timestamp, target_days: pd.DatetimeIndex
) -> tuple[np.ndarray, np.ndarray]:
    """(profile zone x weekday x hour of the same month a year earlier, per zone's borough
    ratio of that month to the four weeks before it). NaN without a year of history."""
    n = len(history.zone_sk)
    ly_start = (origin - pd.DateOffset(years=1)).normalize()
    ly_days = month_days(ly_start)
    s = origin_index(history, ly_start)
    if s < 28 or ly_days[-1] not in history.days or ly_days[-1] >= origin:
        return np.full((n, 7, 24), np.nan), np.full(n, np.nan)
    e = s + len(ly_days)
    month = history.trips[:, s:e, :]
    profile = _weekday_profile(month, history.days[s:e], history.holidays)
    before = history.trips[:, s - 28 : s, :]
    m = _by_borough(month.mean(axis=(1, 2)), history.borough)
    b = _by_borough(before.mean(axis=(1, 2)), history.borough)
    ratio = np.array([m[x] / b[x] if b[x] > 0 else np.nan for x in history.borough])
    return profile, ratio


def borough_trend(history: History, origin: pd.Timestamp) -> np.ndarray:
    """Per zone's borough: trips of the last two weeks before the origin against the two
    weeks before them (two whole weeks each, so weekdays balance out)."""
    o = origin_index(history, origin)
    recent = history.trips[:, o - 14 : o, :].sum(axis=(1, 2))
    before = history.trips[:, o - 28 : o - 14, :].sum(axis=(1, 2))
    r, b = _by_borough(recent, history.borough), _by_borough(before, history.borough)
    return np.array([r[x] / b[x] if b[x] > 0 else np.nan for x in history.borough])


def adjustment(trend: np.ndarray, ly_ratio: np.ndarray) -> np.ndarray:
    """Per zone factor of the adjusted baseline: half of the recent borough trend and the
    month's usual change from last year, each bounded; 1 where unknown."""
    recent = np.where(np.isfinite(trend), 1 + TREND_DAMPING * (trend - 1), 1.0)
    seasonal = np.where(np.isfinite(ly_ratio), ly_ratio, 1.0)
    return np.clip(recent, *TREND_BOUNDS) * np.clip(seasonal, *LY_BOUNDS)


def build(history: History, origin: pd.Timestamp, target_days: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per zone x target day x hour, features only (see the module docstring)."""
    o = origin_index(history, origin)
    if o < 28:
        raise ValueError(f"at least 4 weeks of history are needed before {origin.date()}")
    past = history.trips[:, :o, :]
    past_days = history.days[:o]

    def window(days: int) -> tuple[np.ndarray, pd.DatetimeIndex]:
        start = max(0, o - days)
        return past[:, start:, :], past_days[start:]

    w4, d4 = window(28)
    w8, d8 = window(56)
    naive_4w = _weekday_profile(w4, d4, history.holidays)
    naive_8w = _weekday_profile(w8, d8, history.holidays)
    zone_hour_4w = w4.mean(axis=1)
    level_4w = w4.mean(axis=(1, 2))
    recent = past[:, o - 14 :, :].mean(axis=(1, 2))
    before = past[:, o - 28 : o - 14, :].mean(axis=(1, 2))
    trend_2w = (recent + 0.5) / (before + 0.5)
    tier = tier_of(w8.mean(axis=(1, 2)) / history.scale)  # tiers are in trips an hour
    gap_zone, gap_borough = last_month_gap(history, origin)
    naive_ly, ly_ratio = last_year(history, origin, target_days)
    factor = adjustment(borough_trend(history, origin), ly_ratio)

    n_zones, n_days = len(history.zone_sk), len(target_days)
    z = np.repeat(np.arange(n_zones), n_days * 24)
    d = np.tile(np.repeat(np.arange(n_days), 24), n_zones)
    h = np.tile(np.arange(24), n_zones * n_days)
    weekday = target_days.dayofweek.to_numpy()[d]
    holiday = np.array([day in history.holidays for day in target_days])[d]
    _, borough_code = np.unique(history.borough, return_inverse=True)
    return pd.DataFrame(
        {
            "zone": z,
            "borough": borough_code[z],
            "tier": tier[z],
            "hour": h,
            "weekday": weekday,
            "is_weekend": (weekday >= 5).astype(int),
            "is_holiday": holiday.astype(int),
            "day_of_month": target_days.day.to_numpy()[d],
            "days_ahead": (target_days - origin).days.to_numpy()[d],
            "naive_4w": naive_4w[z, weekday, h],
            "naive_8w": naive_8w[z, weekday, h],
            "zone_hour_4w": zone_hour_4w[z, h],
            "level_4w": level_4w[z],
            "trend_2w": trend_2w[z],
            "gap_last_zone": gap_zone[z],
            "gap_last_borough": gap_borough[z],
            "naive_ly": naive_ly[z, weekday, h],
            "ly_ratio": ly_ratio[z],
            "adj_factor": factor[z],  # adjusted baseline, not a model feature
            "day_index": d,  # position in target_days, not a feature
        }
    )


def actuals(history: History, target_days: pd.DatetimeIndex) -> np.ndarray:
    """Recorded trips in the same row order as build() (zone, day, hour)."""
    idx = [history.days.get_loc(day) for day in target_days]
    return history.trips[:, idx, :].reshape(-1)


def month_days(month_start: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(month_start, month_start + pd.offsets.MonthEnd(0), freq="D")
