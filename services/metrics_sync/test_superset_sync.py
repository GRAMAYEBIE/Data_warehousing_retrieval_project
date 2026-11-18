"""Unit tests: a governed metric is attached to a Superset dataset only when it can run there."""

import json

import superset_sync as sync

FARE = (
    "sum(sum_fare_amount) filter (where quality_status = 'valid') "
    "/ nullif(sum(trip_count) filter (where quality_status = 'valid'), 0)"
)
ACTIVE_HOURS = (
    "count(distinct pickup_date_sk * 100 + pickup_hour) filter (where quality_status = 'valid')"
)


def metric(name, expression, unit="USD", estimate=False):
    return {
        "name": name,
        "label": name.replace("_", " "),
        "description": f"{name} description",
        "config": {
            "meta": {
                "sql_expression": expression,
                "unit": unit,
                "is_estimate": estimate,
                "owner": "AYEBIE GRAM MESCHAC (Data Team)",
            }
        },
    }


def test_columns_ignore_sql_words_and_string_literals():
    assert sync.columns_in(FARE) == {"sum_fare_amount", "quality_status", "trip_count"}
    assert sync.columns_in(ACTIVE_HOURS) == {"pickup_date_sk", "pickup_hour", "quality_status"}


def test_metric_is_attached_only_where_all_its_columns_exist():
    catalog = [metric("avg_fare", FARE, "USD per trip"), metric("active_hours_valid", ACTIVE_HOURS)]
    daily = {"sum_fare_amount", "trip_count", "quality_status", "pickup_date_sk"}
    hourly = {"trip_count", "quality_status", "pickup_date_sk", "pickup_hour"}
    assert [m["metric_name"] for m in sync.metric_payloads(catalog, daily)] == ["avg_fare"]
    assert [m["metric_name"] for m in sync.metric_payloads(catalog, hourly)] == [
        "active_hours_valid"
    ]


def test_payload_copies_the_expression_and_certifies_it():
    [payload] = sync.metric_payloads(
        [metric("avg_fare", FARE, "USD per trip")],
        {"sum_fare_amount", "trip_count", "quality_status"},
    )
    assert payload["expression"] == FARE
    assert payload["d3format"] == "$,.2f"
    assert "certified_by" in json.loads(payload["extra"])["certification"]


def test_quality_shares_are_generated_from_the_dataset_columns():
    columns = {"trip_count", "valid_trip_count", "negative_amount_trip_count", "source_month"}
    names = [m["metric_name"] for m in sync.quality_rate_payloads(columns)]
    assert names == ["negative_amount_share", "valid_share"]


def test_estimates_are_flagged_to_the_viewer():
    [payload] = sync.metric_payloads(
        [metric("est_co2_kg", "sum(sum_trip_distance) * 0.400", "kg CO2 (estimate)", True)],
        {"sum_trip_distance"},
    )
    assert payload["warning_text"] == "Estimate, not a measurement."
    assert payload["description"].endswith("ESTIMATE.")
