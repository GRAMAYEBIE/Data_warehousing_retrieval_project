"""Unit tests of the retrieval for the planner and of the plan repairs."""

from pathlib import Path

import pytest
import yaml
from test_assistant import CATALOG, COLUMNS, ROWS, FakeStore, assistant, plan, scripted_ollama

from assistant import retrieval
from assistant.catalog import DIMENSIONS, Catalog
from assistant.grounding import ground, named_period
from assistant.schemas import DateRange, Filter, Intent, Period, QueryPlan
from assistant.validator import PlanRejected

EVAL_CASES = next(
    (
        folder / "evals" / "cases.yaml"
        for folder in [*Path(__file__).resolve().parents, Path("/")]
        if (folder / "evals" / "cases.yaml").exists()
    ),
    Path("evals/cases.yaml"),  # absent: the test is skipped
)
GOVERNED = {
    "trips", "total_revenue", "avg_fare", "avg_tip", "tip_rate", "avg_distance",
    "avg_duration", "revenue_per_mile", "trips_per_active_hour", "airport_trips",
    "congestion_fee_revenue", "valid_trip_rate", "est_co2_kg",
}  # fmt: skip
REAL_MEMBERS = {
    "pickup_borough": {"Bronx", "Brooklyn", "EWR", "Manhattan", "Queens", "Staten Island"},
    "pickup_zone": {"JFK Airport", "LaGuardia Airport", "Newark Airport"},
    "payment_type": {"Cash", "Credit card", "Dispute", "No charge", "Voided trip"},
    "day_type": {"Public holiday", "Weekday", "Weekend"},
    "service_period": {"AM peak", "PM peak", "Late night", "Off-peak"},
}


def test_values_are_linked_from_names_aliases_and_typos():
    links = retrieval.link_values("Trips in Manhatan paid by card at JFK last month", CATALOG)
    found = {(link.dimension, link.value) for link in links}
    assert found == {
        ("pickup_borough", "Manhattan"),  # typo
        ("payment_type", "Credit card"),  # alias
        ("pickup_zone", "JFK Airport"),  # alias
    }


def test_no_value_named_means_no_filter():
    text = retrieval.describe_links(retrieval.link_values("Biggest drop in trips", CATALOG))
    assert "none" in text and "Do not add a filter" in text


def test_a_borough_inside_a_zone_name_is_not_the_borough():
    catalog = Catalog(
        metrics={},
        members={"pickup_borough": ["Manhattan"], "pickup_zone": ["Manhattan Valley"]},
        months=[],
        published_run="",
        published_at="",
    )
    links = retrieval.link_values("Trips from Manhattan Valley", catalog)
    assert [(link.dimension, link.value) for link in links] == [("pickup_zone", "Manhattan Valley")]


def test_every_example_plan_uses_the_governed_vocabulary():
    for example in retrieval.load_examples():
        parsed = QueryPlan.model_validate(example["plan"])
        assert set(parsed.metrics) <= GOVERNED, example["question"]
        assert set(parsed.dimensions) <= set(DIMENSIONS), example["question"]
        for f in parsed.filters:
            assert set(f.values) <= REAL_MEMBERS[f.dimension], example["question"]


def test_examples_are_not_the_evaluation_questions():
    """Otherwise the evaluation would measure memorisation, not planning."""
    if not EVAL_CASES.exists():
        pytest.skip("evaluation pack not available (container image)")
    cases = yaml.safe_load(EVAL_CASES.read_text(encoding="utf-8"))["cases"]
    asked = [set(retrieval._words(c["question"])) for c in cases]
    for example in retrieval.load_examples():
        words = set(retrieval._words(example["question"]))
        for case in asked:
            overlap = len(words & case) / len(words | case)
            assert overlap < 0.75, f"example too close to an evaluation case: {example}"


def test_the_closest_examples_are_retrieved():
    found = retrieval.similar_examples("Top 3 pickup zones by revenue this month")
    assert found[0]["plan"]["intent"] == "rank"


def test_only_vocabulary_mistakes_are_repairable():
    assert PlanRejected(["invalid filter: pickup_zone has no value 'Queens'"]).repairable
    assert not PlanRejected(["unsupported date range: 2023-03 is not published"]).repairable
    assert not PlanRejected(
        ["invalid filter: x", "conflicting filters on pickup_borough: no row can match"]
    ).repairable


class SequenceLLM:
    """Returns the given plans in order, one per planning call."""

    def __init__(self, plans, narrative=""):
        self.plans, self.narrative, self.messages = list(plans), narrative, []

    def structured(self, system, user, model_cls):
        self.messages.append(user)
        return self.plans.pop(0)

    def chat(self, system, user, schema=None, max_tokens=None):
        return self.narrative

    def available(self):
        return True


def test_a_vocabulary_mistake_is_repaired_once_and_reported():
    a = assistant(store=FakeStore(COLUMNS, ROWS))
    bad = plan(intent=Intent.rank, metrics=["trip_volume"], dimensions=["pickup_zone"])
    good = plan(intent=Intent.rank, metrics=["trips"], dimensions=["pickup_zone"])
    a.llm = SequenceLLM([bad, good], narrative="JFK Airport led with 152,340 trips.")
    answer = a.ask("Which pickup zones had the most trips?")
    assert answer.status == "answered"
    assert answer.reasons[0].startswith("plan repaired after validation: unknown metric")
    assert "rejected by the validator" in a.llm.messages[1]


def test_a_copied_filter_is_removed_and_the_named_period_applied():
    # Observed with retrieval on: the filter of an example was copied, Brooklyn and
    # "last month" were ignored.
    copied = plan(metrics=["trips"], filters=[Filter(dimension="payment_type", values=["Cash"])])
    result = ground(copied, "What was the trips count in Brooklyn last month?", CATALOG, [])
    assert result.plan.filters == []
    assert result.plan.date_range == DateRange(period=Period.previous_month)
    assert any("filter removed" in n and "Cash" in n for n in result.notes)
    assert result.missing and "Brooklyn" in result.missing[0]
    assert PlanRejected(result.missing).repairable


def test_a_follow_up_naming_a_value_replaces_the_previous_one():
    # Observed in the evaluation: "And for Queens?" after Brooklyn kept both boroughs.
    previous = [Filter(dimension="pickup_borough", values=["Brooklyn"])]
    both = plan(
        metrics=["trips"],
        filters=[Filter(dimension="pickup_borough", values=["Brooklyn", "Queens"])],
    )
    result = ground(both, "And for Queens?", CATALOG, previous)
    assert result.plan.filters == [Filter(dimension="pickup_borough", values=["Queens"])]
    kept = ground(both, "And Queens as well?", CATALOG, previous)
    assert kept.plan.filters[0].values == ["Brooklyn", "Queens"]


def test_an_exclusion_needs_words_of_exclusion():
    # Observed: "tip rate in Brooklyn" planned as Brooklyn = and Brooklyn != together.
    both = plan(
        metrics=["trips"],
        filters=[
            Filter(dimension="pickup_borough", values=["Brooklyn"]),
            Filter(dimension="pickup_borough", operator="!=", values=["Brooklyn"]),
        ],
    )
    result = ground(both, "Trips in Brooklyn", CATALOG, [])
    assert result.plan.filters == [Filter(dimension="pickup_borough", values=["Brooklyn"])]
    assert any("exclusion removed" in n for n in result.notes)
    kept = ground(both, "Trips everywhere except Brooklyn", CATALOG, [])
    assert any(f.operator == "!=" for f in kept.plan.filters)


def test_a_follow_up_without_measure_or_period_keeps_the_previous_ones():
    previous = plan(
        metrics=["tip_rate"],
        date_range=DateRange(period=Period.previous_month),
        filters=[Filter(dimension="pickup_borough", values=["Brooklyn"])],
    )
    invented = plan(
        metrics=["revenue_per_mile", "avg_fare"],
        filters=[Filter(dimension="pickup_borough", values=["Queens"])],
    )
    result = ground(invented, "And for Queens?", CATALOG, previous.filters, previous)
    assert result.plan.metrics == ["tip_rate"]
    assert result.plan.date_range == DateRange(period=Period.previous_month)
    assert result.plan.filters == [Filter(dimension="pickup_borough", values=["Queens"])]


def test_follow_up_filters_are_kept_when_they_come_from_the_conversation():
    previous = [Filter(dimension="payment_type", values=["Cash"])]
    follow = plan(
        metrics=["trips"],
        filters=[
            Filter(dimension="payment_type", values=["Cash"]),
            Filter(dimension="pickup_borough", values=["Queens"]),
        ],
    )
    result = ground(follow, "And for Queens?", CATALOG, previous)
    assert len(result.plan.filters) == 2 and not result.notes and not result.missing


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Trips in March 2023", DateRange(period=Period.custom, start_month="2023-03",
                                          end_month="2023-03")),
        ("Revenue from 2024-12 to 2025-02", DateRange(period=Period.custom,
                                                      start_month="2024-12",
                                                      end_month="2025-02")),
        ("Trips over the last three months", DateRange(period=Period.last_3_months)),
        ("Average fare this month", DateRange(period=Period.latest_month)),
        ("Average fare by borough", None),
    ],
)  # fmt: skip
def test_named_periods(question, expected):
    assert named_period(question) == expected


def test_a_month_outside_coverage_is_explained_even_if_the_model_says_unsupported():
    a = assistant(store=FakeStore(COLUMNS, ROWS))
    a.llm = SequenceLLM([plan(intent=Intent.unsupported, unsupported_reason="no data")])
    answer = a.ask("How many trips did we have in March 2023?")
    assert answer.status == "rejected"
    assert "2023-03 is not published" in answer.reasons[0]
    assert "2024-12 to 2025-02" in answer.reasons[0]


def test_a_date_outside_the_coverage_is_never_repaired():
    a = assistant(store=FakeStore(COLUMNS, ROWS))
    outside = plan(
        metrics=["trips"],
        date_range=DateRange(period=Period.custom, start_month="2023-03", end_month="2023-03"),
    )
    a.llm = SequenceLLM([outside])
    answer = a.ask("How many trips in March 2023?")
    assert answer.status == "rejected" and "unsupported date range" in answer.reasons[0]
    assert len(a.llm.messages) == 1  # no second call


def test_a_json_syntax_error_is_retried_under_the_json_grammar():
    llm, calls = scripted_ollama(
        ['{"intent": "lookup", "metrics": ["trips"', '{"intent": "lookup", "metrics": ["trips"]}']
    )
    assert llm.structured("sys", "q", QueryPlan).metrics == ["trips"]
    assert calls[0]["schema"] is None and calls[1]["schema"] == "json"
