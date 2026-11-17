"""Unit tests of the pipeline operations logic (no Airflow, no database needed)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from nyc_taxi_ops import dbt_results, publish, signals


@pytest.mark.parametrize(
    ("rows", "previous", "status"),
    [
        (3_475_226, 3_668_371, "ok"),  # 2025-01 vs 2024-12: -5.26 %
        (2_800_000, 3_668_371, "warn"),  # -23.7 %
        (1_000_000, 3_668_371, "fail"),  # -72.7 %: truncated file?
        (3_475_226, None, "ok"),  # first month: nothing to compare with
        (0, 3_668_371, "fail"),  # empty month
    ],
)
def test_volume_signal(rows, previous, status):
    assert signals.volume_signal(rows, previous).status == status


def test_volume_signal_value_is_the_percentage_change():
    assert signals.volume_signal(3_475_226, 3_668_371).value == pytest.approx(-5.26, abs=0.01)


@pytest.mark.parametrize(
    ("suspicious", "invalid", "status"),
    [(152_379, 144_957, "ok"), (400_000, 100_000, "warn"), (500_000, 300_000, "fail")],
)
def test_rejected_signal(suspicious, invalid, status):
    assert signals.rejected_signal(3_475_226, suspicious, invalid).status == status


def test_rejected_signal_fails_on_empty_silver():
    assert signals.rejected_signal(0, 0, 0).status == "fail"


def test_late_data_signal():
    assert signals.late_data_signal(3_475_226, 22).status == "ok"
    assert signals.late_data_signal(1_000, 5).status == "warn"


def test_freshness_signal_never_fails_only_warns():
    now = datetime(2026, 11, 17)
    assert signals.freshness_signal(now - timedelta(days=1), now).status == "ok"
    assert signals.freshness_signal(now - timedelta(days=400), now).status == "warn"
    assert signals.freshness_signal(None, now).status == "warn"


def test_freshness_signal_accepts_database_timestamps_with_time_zone():
    # Regression: PostgreSQL returns timestamptz; the first real run compared it with a
    # naive datetime and failed with "can't subtract offset-naive and offset-aware".
    last_load = datetime(2026, 11, 16, 23, 0, tzinfo=UTC)
    for now in (datetime(2026, 11, 17, 23, 0), datetime(2026, 11, 17, 23, 0, tzinfo=UTC)):
        signal = signals.freshness_signal(last_load, now)
        assert signal.value == pytest.approx(1.0)
        assert signal.status == "ok"


def test_test_pass_signal_fails_below_100_percent():
    assert signals.test_pass_signal(72, 72).status == "ok"
    assert signals.test_pass_signal(71, 72).status == "fail"
    assert signals.test_pass_signal(0, 0).status == "warn"


class FakeCursor:
    """Answers the three queries of publish.check_gate in order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.current = self.answers.pop(0)

    def fetchall(self):
        return self.current

    def fetchone(self):
        return self.current


class FakeConnection:
    def __init__(self, answers):
        self.answers = answers

    def cursor(self):
        return FakeCursor(self.answers)


def test_gate_opens_when_everything_is_clean():
    conn = FakeConnection([[], [], (0,)])
    assert publish.check_gate(conn, "run")["gate"] == "open"


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        ([[("2025-01-01", 12, 0)], [], (0,)], "reconciliation gap in 2025-01-01"),
        ([[], [("volume_change_vs_prior_month", -72.7)], (0,)], "volume_change_vs_prior_month"),
        ([[], [], (3,)], "3 dbt test(s) failed"),
    ],
)
def test_gate_closes_with_the_reason(answers, reason):
    with pytest.raises(publish.GateClosed, match=re.escape(reason)):
        publish.check_gate(FakeConnection(answers), "run")


def test_only_test_nodes_are_kept_from_run_results():
    run_results = {
        "results": [
            {"unique_id": "model.nyc_taxi.fct_trip", "status": "success"},
            {
                "unique_id": "test.nyc_taxi.unique_fct_trip_trip_sk.abc",
                "status": "pass",
                "failures": 0,
                "execution_time": 1.5,
                "message": None,
            },
            {
                "unique_id": "test.nyc_taxi.assert_x",
                "status": "fail",
                "failures": 3,
                "execution_time": 2.0,
                "message": "Got 3 results",
            },
        ]
    }
    rows = dbt_results.test_results(run_results)
    assert [r["status"] for r in rows] == ["pass", "fail"]
    assert rows[1]["failures"] == 3


def test_missing_run_results_file_gives_no_rows(tmp_path):
    assert dbt_results.test_results(dbt_results.read_run_results(str(tmp_path))) == []
