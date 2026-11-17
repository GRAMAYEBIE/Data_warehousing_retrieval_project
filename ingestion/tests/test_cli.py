"""Unit tests for the command line: argument parsing and exit codes."""

from datetime import date

import pytest

from ingestion import cli
from ingestion.pipeline import ContractViolation, NothingToLoad
from ingestion.source import FileValidationError, SourceNotAvailable


def test_month_is_parsed_to_first_day():
    assert cli.parse_month("2025-03") == date(2025, 3, 1)


@pytest.mark.parametrize("bad", ["2025", "2025-13", "march", "2025-03-01"])
def test_bad_month_is_rejected(bad):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["land", "--month", bad])


def test_force_is_only_accepted_where_it_means_something():
    assert cli.build_parser().parse_args(["land", "--month", "2025-01", "--force"]).force
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["load", "--month", "2025-01", "--force"])


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SourceNotAvailable("missing"), 2),
        (FileValidationError("bad file"), 3),
        (ContractViolation("bad schema"), 3),
        (NothingToLoad("nothing"), 4),
        (RuntimeError("boom"), 1),
    ],
)
def test_each_failure_mode_has_its_exit_code(monkeypatch, error, code):
    def fail(args, settings):
        raise error

    monkeypatch.setattr(cli, "run", fail)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: None))
    assert cli.main(["load", "--month", "2025-01"]) == code


def test_success_exits_zero(monkeypatch):
    monkeypatch.setattr(cli, "run", lambda args, settings: "already_loaded")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: None))
    assert cli.main(["load", "--month", "2025-01"]) == 0
