"""Unit tests for the source contract and schema-drift detection."""

from pathlib import Path

import pyarrow as pa
import pytest

from ingestion.contract import check_schema, load_contract, schema_hash

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"

FAMILY_TYPES = {
    "integer": pa.int64(),
    "number": pa.float64(),
    "timestamp": pa.timestamp("us"),
    "string": pa.string(),
}


def schema_for(contract, drop=(), extra=(), rename=None):
    rename = rename or {}
    fields = [
        pa.field(rename.get(c.name, c.name), FAMILY_TYPES[c.family])
        for c in contract.columns
        if c.name not in drop
    ]
    fields.extend(pa.field(name, pa.float64()) for name in extra)
    return pa.schema(fields)


def test_contract_version_follows_the_month():
    assert load_contract(CONTRACTS, "yellow", "2024-12").version == "v2024"
    assert load_contract(CONTRACTS, "yellow", "2025-01").version == "v2025"
    assert load_contract(CONTRACTS, "yellow", "2025-12").version == "v2025"


def test_no_contract_before_first_version():
    with pytest.raises(LookupError):
        load_contract(CONTRACTS, "yellow", "2010-12")


def test_cbd_congestion_fee_is_the_only_difference_between_versions():
    v2024 = set(load_contract(CONTRACTS, "yellow", "2024-12").column_names)
    v2025 = set(load_contract(CONTRACTS, "yellow", "2025-01").column_names)
    assert v2025 - v2024 == {"cbd_congestion_fee"}
    assert v2024 - v2025 == set()


def test_conforming_schema_has_no_drift():
    contract = load_contract(CONTRACTS, "yellow", "2025-01")
    report = check_schema(schema_for(contract), contract)
    assert not report.has_drift
    assert not report.blocking


def test_column_name_case_is_ignored():
    contract = load_contract(CONTRACTS, "yellow", "2025-01")
    schema = schema_for(contract, rename={"airport_fee": "Airport_fee", "vendorid": "VendorID"})
    assert not check_schema(schema, contract).has_drift


def test_new_column_is_reported_but_not_blocking():
    # A 2025 file checked against the 2024 contract: the new fee column is drift.
    contract = load_contract(CONTRACTS, "yellow", "2024-12")
    report = check_schema(schema_for(contract, extra=["cbd_congestion_fee"]), contract)
    assert report.unknown_columns == ["cbd_congestion_fee"]
    assert not report.blocking


def test_missing_required_column_is_blocking():
    contract = load_contract(CONTRACTS, "yellow", "2025-01")
    report = check_schema(schema_for(contract, drop=["total_amount"]), contract)
    assert report.missing_required == ["total_amount"]
    assert report.blocking


def test_wrong_type_family_is_blocking():
    contract = load_contract(CONTRACTS, "yellow", "2025-01")
    fields = [
        pa.field(c.name, pa.string() if c.name == "fare_amount" else FAMILY_TYPES[c.family])
        for c in contract.columns
    ]
    report = check_schema(pa.schema(fields), contract)
    assert report.type_mismatches and "fare_amount" in report.type_mismatches[0]
    assert report.blocking


def test_schema_hash_is_order_and_case_independent_but_type_sensitive():
    a = pa.schema([pa.field("VendorID", pa.int32()), pa.field("fare_amount", pa.float64())])
    b = pa.schema([pa.field("fare_amount", pa.float64()), pa.field("vendorid", pa.int32())])
    c = pa.schema([pa.field("vendorid", pa.int64()), pa.field("fare_amount", pa.float64())])
    assert schema_hash(a) == schema_hash(b)
    assert schema_hash(a) != schema_hash(c)
