"""Tests of the forecasting method on synthetic data (no database, no MLflow).

The data has the shape of the real one: a few busy zones, a few quiet ones and sparse ones
with mostly zero hours, a daily and a weekly cycle, a public holiday.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from forecasting import evaluate, pipeline
from forecasting.data import History, from_frames
from forecasting.features import FEATURES, build, month_days, tier_of
from forecasting.model import origins

LEVELS = {1: 60.0, 2: 25.0, 3: 5.0, 4: 0.8, 5: 0.05}  # mean trips per hour, per zone
BOROUGHS = {1: "Manhattan", 2: "Queens", 3: "Brooklyn", 4: "Bronx", 5: "Staten Island"}
HOLIDAY = pd.Timestamp("2025-01-20")


def synthetic(months: int = 6, seed: int = 0) -> History:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2024-12-01", periods=31 * months, freq="D")
    days = days[days < pd.Timestamp("2024-12-01") + pd.DateOffset(months=months)]
    hour_shape = 0.3 + np.sin(np.linspace(0, np.pi, 24)) ** 2
    rows = []
    for zone, level in LEVELS.items():
        for day in days:
            week = 1.15 if day.dayofweek in (3, 4) else 0.85 if day.dayofweek == 6 else 1.0
            holiday = 0.5 if day == HOLIDAY else 1.0
            for hour, value in enumerate(rng.poisson(level * hour_shape * week * holiday)):
                if value:
                    rows.append((day, hour, zone, value))
    hourly = pd.DataFrame(rows, columns=["date_day", "pickup_hour", "pickup_zone_sk", "trips"])
    zones = pd.DataFrame(
        {"zone_sk": list(BOROUGHS), "zone_name": [f"Zone {z}" for z in BOROUGHS],
         "borough": list(BOROUGHS.values())}
    )  # fmt: skip
    return from_frames(hourly, zones, {HOLIDAY})


@pytest.fixture(scope="module")
def history() -> History:
    return synthetic()


def test_the_grid_is_dense_with_zero_hours(history):
    assert history.trips.shape == (5, len(history.days), 24)
    sparse = history.trips[4]
    assert (sparse == 0).mean() > 0.8  # the sparse zone is mostly empty hours, kept as zeros


def test_no_feature_sees_the_month_it_forecasts(history):
    """Changing every value of the target month (and after) must not move any feature."""
    origin = pd.Timestamp("2025-03-01")
    days = month_days(origin)
    before = build(history, origin, days)
    o = int((history.days < origin).sum())
    tampered = History(**{**history.__dict__, "trips": history.trips.copy()})
    tampered.trips[:, o:, :] = 999.0
    after = build(tampered, origin, days)
    pd.testing.assert_frame_equal(before[FEATURES], after[FEATURES])


def test_the_baseline_is_the_same_weekday_and_hour_over_four_weeks(history):
    origin = pd.Timestamp("2025-04-01")
    frame = build(history, origin, month_days(origin))
    row = frame[(frame.zone == 0) & (frame.day_index == 0) & (frame.hour == 12)].iloc[0]
    o = int((history.days < origin).sum())
    window = history.days[o - 28 : o]
    same = [i for i, d in enumerate(window, start=o - 28) if d.dayofweek == origin.dayofweek]
    assert row.naive_4w == pytest.approx(history.trips[0, same, 12].mean())


def test_holidays_are_left_out_of_the_profiles(history):
    origin = pd.Timestamp("2025-02-01")  # the 4-week window holds the holiday (a Monday)
    frame = build(history, origin, month_days(origin))
    monday = frame[(frame.zone == 0) & (frame.weekday == 0) & (frame.hour == 12)].iloc[0]
    o = int((history.days < origin).sum())
    window = range(o - 28, o)
    mondays = [i for i in window if history.days[i].dayofweek == 0 and history.days[i] != HOLIDAY]
    assert monday.naive_4w == pytest.approx(history.trips[0, mondays, 12].mean())


def test_tiers_follow_the_hourly_level():
    assert list(tier_of(np.array([60.0, 20.0, 5.0, 0.5, 0.05, 0.0]))) == [0, 0, 1, 2, 3, 3]


def test_wmape_is_defined_with_zero_hours_and_weighted_by_volume():
    actual = np.array([0.0, 0.0, 100.0])
    assert evaluate.wmape(actual, np.array([1.0, 1.0, 90.0])) == pytest.approx(12 / 100)
    assert np.isnan(evaluate.wmape(np.zeros(3), np.ones(3)))


def test_origins_need_four_weeks_of_history(history):
    assert origins(history)[0] == pd.Timestamp("2025-01-01")  # December is history only


def test_a_full_run_validates_on_the_last_month_and_forecasts_the_next(history):
    result = pipeline.run(history)
    assert result.validated_month == "2025-05" and result.forecast_month == "2025-06"
    assert "2025-05" not in result.train_months
    assert len(result.forecast) == 5 * 30 * 24
    assert (result.forecast.lower <= result.forecast.predicted).all()
    assert (result.forecast.predicted <= result.forecast.upper).all()
    assert result.forecast.loc[result.forecast.zone_sk == 5, "low_confidence"].all()
    assert set(result.evaluation.segment_type) == {"overall", "borough", "tier", "borough_day"}
    overall = result.evaluation[result.evaluation.segment_type == "overall"].iloc[0]
    assert 0 < overall.coverage_80 <= 1
    # Stable synthetic seasonality: the model must at least match the naive baseline.
    assert overall.wmape <= overall.baseline_wmape * 1.05
    daily = result.daily
    assert (daily.lower <= daily.predicted).all() and (daily.predicted <= daily.upper).all()


def test_fewer_than_six_months_is_never_publishable():
    result = pipeline.run(synthetic(months=4, seed=1))
    assert not result.publishable
    assert any("6 required" in r for r in result.reasons)
