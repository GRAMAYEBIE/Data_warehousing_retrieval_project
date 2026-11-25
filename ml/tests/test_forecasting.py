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


@pytest.fixture(scope="module")
def result(history):
    return pipeline.run(history)


def test_a_run_backtests_three_months_and_forecasts_the_next(result):
    assert sorted(set(result.backtests.month)) == ["2025-03", "2025-04", "2025-05"]
    assert set(result.backtests.method) == {"model", "baseline"}
    assert result.validated_month == "2025-05" and result.forecast_month == "2025-06"
    assert result.champion in {"model", "baseline"}
    assert set(result.forecast["method"]) == {result.champion}
    assert len(result.forecast) == 5 * 30 * 24
    assert (result.forecast.lower <= result.forecast.predicted).all()
    assert (result.forecast.predicted <= result.forecast.upper).all()
    assert result.forecast.loc[result.forecast.zone_sk == 5, "low_confidence"].all()
    assert set(result.evaluation.segment_type) == {"overall", "borough", "tier", "borough_day"}
    overall = result.evaluation[result.evaluation.segment_type == "overall"].iloc[0]
    assert 0.5 < overall.coverage_80 <= 1  # an 80 % interval, built from earlier months only
    daily = result.daily
    assert (daily.lower <= daily.predicted).all() and (daily.predicted <= daily.upper).all()


def test_a_backtest_never_reads_after_the_month_it_forecasts(history):
    """Tampering with everything after the month changes nothing in its backtest."""
    starts = origins(history)
    start, prior = starts[2], starts[:2]  # March, trained on January and February
    before = pipeline.backtest(history, start, prior).frame
    tampered = History(**{**history.__dict__, "trips": history.trips.copy()})
    end = int((history.days <= month_days(start)[-1]).sum())
    tampered.trips[:, end:, :] = 999.0
    after = pipeline.backtest(tampered, start, prior).frame
    pd.testing.assert_frame_equal(before, after)


def _scores(model: list[float], baseline: list[float], high=(0.1, 0.1)) -> pd.DataFrame:
    return pd.DataFrame(
        {"model_wmape": model, "baseline_wmape": baseline,
         "model_high": [high[0]] * len(model), "baseline_high": [high[1]] * len(model)}
    )  # fmt: skip


def test_the_model_is_promoted_only_when_it_wins_most_months():
    # The real case of 2026-11: the baseline won March and April, the model May only.
    assert pipeline.choose(_scores([0.210, 0.217, 0.208], [0.192, 0.194, 0.213]))[0] == "baseline"
    assert pipeline.choose(_scores([0.18, 0.19, 0.25], [0.20, 0.21, 0.22]))[0] == "model"
    # Wins most months but loses on average: not promoted.
    assert pipeline.choose(_scores([0.19, 0.19, 0.40], [0.20, 0.20, 0.21]))[0] == "baseline"
    # Better overall but worse on the busy zones that carry 92 % of trips: not promoted.
    worse_high = _scores([0.18, 0.18, 0.18], [0.20, 0.20, 0.20], high=(0.20, 0.15))
    assert pipeline.choose(worse_high)[0] == "baseline"


def test_the_baseline_interval_widens_with_the_level():
    frame = pd.DataFrame({"baseline": np.repeat([1.0, 50.0], 500)})
    rng = np.random.default_rng(3)
    frame["actual"] = rng.poisson(frame["baseline"])
    bands = pipeline.baseline_bands([frame])
    lower, upper = pipeline.baseline_interval(np.array([1.0, 50.0]), bands)
    assert (upper - lower)[1] > (upper - lower)[0] > 0
    assert lower[1] < 50 < upper[1]


def test_revenue_uses_the_same_method_with_tiers_in_trips():
    """Revenue (USD) = trips x 25 here: same tiers, same champion, values 25 times larger."""
    from forecasting.data import TARGETS

    trips = synthetic()
    revenue = History(**{**trips.__dict__, "trips": trips.trips * 25.0, "target": "revenue",
                         "scale": TARGETS["revenue"].scale})  # fmt: skip
    origin = pd.Timestamp("2025-04-01")
    a = build(trips, origin, month_days(origin))
    b = build(revenue, origin, month_days(origin))
    assert (a["tier"] == b["tier"]).all()
    assert np.allclose(b["naive_4w"], a["naive_4w"] * 25)
    result = pipeline.run(revenue)
    assert result.target == "revenue" and (result.forecast.predicted >= 0).all()
    assert (result.forecast.lower <= result.forecast.upper).all()


def test_each_target_is_registered_under_its_own_model_name(history, monkeypatch):
    """Regression: a loop variable once replaced the model name ("coverage_80")."""
    from forecasting import tracking

    calls = {}

    class Info:
        registered_model_version = None

    monkeypatch.setattr(tracking.mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(tracking.mlflow, "set_experiment", lambda n: calls.setdefault("exp", n))
    monkeypatch.setattr(tracking.mlflow, "set_tags", lambda tags: None)
    monkeypatch.setattr(tracking.mlflow, "log_params", lambda params: None)
    monkeypatch.setattr(tracking.mlflow, "log_metrics", lambda metrics: None)
    monkeypatch.setattr(tracking.mlflow, "log_text", lambda text, path: None)

    def log_model(model, name, registered_model_name):
        calls["model"] = registered_model_name
        return Info()

    monkeypatch.setattr(tracking.mlflow.lightgbm, "log_model", log_model)

    class Run:
        info = type("I", (), {"run_id": "r"})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tracking.mlflow, "start_run", lambda run_name: Run())
    result = pipeline.run(synthetic(months=6, seed=2))
    tracking.log(result, "test", ["2025-05"], "http://unused")
    assert calls == {"exp": "demand_forecast", "model": "demand_forecast"}


def test_fewer_than_six_months_is_never_publishable():
    result = pipeline.run(synthetic(months=4, seed=1))
    assert not result.publishable
    assert any("6 required" in r for r in result.reasons)


# ------------------------------------------------------------------ forecast against actual
def test_a_replay_sees_only_the_months_before_the_one_it_forecasts(history):
    from forecasting.check import history_until

    past = history_until(history, "2025-03")
    assert past.months == ["2024-12", "2025-01", "2025-02", "2025-03"]
    assert past.trips.shape[1] == len(past.days) and past.days[-1] == pd.Timestamp("2025-03-31")
    assert np.array_equal(past.trips, history.trips[:, : len(past.days), :])


@pytest.fixture(scope="module")
def checked(history):
    from forecasting.check import compare, history_until

    replayed = pipeline.run(history_until(history, "2025-04"))
    return replayed, compare(history, replayed.forecast, replayed.daily, 0.05)


def test_a_forecast_is_checked_against_what_was_recorded(history, checked):
    replayed, check = checked
    assert replayed.forecast_month == check.month == "2025-05"
    s = check.scores.set_index(["segment_type", "segment"])
    may = history.trips[:, history.days.month == 5, :]
    assert s.loc[("overall", "all"), "actual"] == pytest.approx(may.sum())
    expected = replayed.forecast.predicted.sum()
    assert s.loc[("overall", "all"), "predicted"] == pytest.approx(expected)
    assert {"overall", "borough", "tier", "borough_day"} <= set(check.scores.segment_type)
    assert len(check.daily) == 5 * 31 and check.actual_wmape < 0.3 and check.status == "ok"
    # The borough-day coverage is that of the borough-day range planners read.
    inside = (check.daily.actual >= check.daily.lower) & (check.daily.actual <= check.daily.upper)
    assert s.loc[("borough_day", "all"), "coverage_80"] == pytest.approx(inside.mean())


def test_a_month_not_recorded_yet_cannot_be_checked(history, checked):
    from forecasting.check import compare, history_until

    replayed, _ = checked
    with pytest.raises(ValueError, match="not fully recorded"):
        compare(history_until(history, "2025-04"), replayed.forecast, replayed.daily, 0.05)


def test_drift_is_an_error_well_above_what_the_backtests_promised(history, checked):
    from forecasting.check import compare, status_of

    assert status_of(0.08, 0.06) == "ok"  # above, but within 1.5 times
    assert status_of(0.12, 0.06) == "drift"
    assert status_of(0.04, 0.02) == "ok"  # twice as high but only 2 points: noise
    assert status_of(0.30, None) == "ok"  # nothing promised
    replayed, _ = checked
    doubled = replayed.forecast.assign(predicted=replayed.forecast.predicted * 2)
    daily = replayed.daily.assign(predicted=replayed.daily.predicted * 2)
    check = compare(history, doubled, daily, 0.05)
    assert check.status == "drift"
    assert check.scores.set_index(["segment_type", "segment"]).loc[
        ("overall", "all"), "bias"
    ] == pytest.approx(1.0, abs=0.15)
