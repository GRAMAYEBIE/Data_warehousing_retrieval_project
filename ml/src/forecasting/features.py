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
  days ahead of the origin.

Public holidays are left out of the profiles: a Christmas Day is not a typical Wednesday.
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
]
CATEGORICAL = ["zone", "borough"]


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
    tier = tier_of(w8.mean(axis=(1, 2)))

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
            "day_index": d,  # position in target_days, not a feature
        }
    )


def actuals(history: History, target_days: pd.DatetimeIndex) -> np.ndarray:
    """Recorded trips in the same row order as build() (zone, day, hour)."""
    idx = [history.days.get_loc(day) for day in target_days]
    return history.trips[:, idx, :].reshape(-1)


def month_days(month_start: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(month_start, month_start + pd.offsets.MonthEnd(0), freq="D")
