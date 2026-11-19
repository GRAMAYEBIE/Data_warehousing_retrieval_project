"""Unit tests: Superset refresh after a publication."""

from pathlib import Path

import pytest

from nyc_taxi_ops import bi_refresh


def test_dashboards_status_follows_the_publication_and_the_refresh():
    assert bi_refresh.dashboards_status(False, None) is None  # nothing published
    assert bi_refresh.dashboards_status(True, bi_refresh.REFRESHED) == "refreshed"
    assert bi_refresh.dashboards_status(True, bi_refresh.SUPERSET_DOWN).startswith("not refreshed")
    assert bi_refresh.dashboards_status(True, None) == "refresh failed"  # task failed


def test_sync_runs_before_the_dashboards_are_rebuilt():
    scripts = [cmd[1] for cmd in bi_refresh.commands(Path("semantic_manifest.json"))]
    # superset_sync updates the datasets (new cache key) before dashboards.py warms it.
    assert scripts == ["metrics_sync.py", "superset_sync.py", "dashboards.py"]


def test_superset_down_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(bi_refresh, "superset_running", lambda *a, **k: False)
    assert bi_refresh.refresh({}, Path("m.json")) == bi_refresh.SUPERSET_DOWN


def test_a_failing_command_fails_the_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(bi_refresh, "superset_running", lambda *a, **k: True)
    monkeypatch.setattr(bi_refresh, "METRICS_SYNC_DIR", tmp_path)
    monkeypatch.setattr(bi_refresh, "PYTHON", "python")
    with pytest.raises(RuntimeError, match="metrics_sync.py failed"):
        bi_refresh.refresh(dict(__import__("os").environ), Path("missing.json"))


def test_unreachable_superset_is_not_running():
    assert not bi_refresh.superset_running("http://127.0.0.1:9", timeout=1)
