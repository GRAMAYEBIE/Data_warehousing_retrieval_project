"""The contract and the consumer's batch logic, without Kafka or a database."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from stream.consumer import split
from stream.contract import Rejected, decode, encode

ROW = {
    "VendorID": 2,
    "tpep_pickup_datetime": datetime(2025, 6, 1, 0, 3, 12),
    "tpep_dropoff_datetime": datetime(2025, 6, 1, 0, 15, 40),
    "passenger_count": float("nan"),  # the files carry NaN for missing values
    "trip_distance": 2.4,
    "PULocationID": 161,
    "DOLocationID": 236,
    "payment_type": 1,
    "fare_amount": 13.5,
    "tip_amount": 3.0,
    "total_amount": 21.3,
}


def test_a_row_of_the_monthly_file_round_trips_through_a_message():
    key, value = encode("2025-06", 1204, ROW)
    assert key == b"161"  # keyed by pickup zone: one zone stays in order on a partition
    trip = decode(value)
    assert trip.source_month == date(2025, 6, 1) and trip.file_row_number == 1204
    assert trip.pickup_ts == ROW["tpep_pickup_datetime"] and trip.pu_location_id == 161
    assert trip.passenger_count is None and trip.total_amount == 21.3


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"schema": "yellow_trip/v0"}, "unknown schema"),
        ({"pu": None}, "missing field"),
        ({"pu": 999}, "unknown zone"),
        ({"pickup": "yesterday"}, "bad date"),
        ({"distance": "2.4"}, "not a number"),
        ({"distance": -1.0}, "impossible value"),
        ({"vendor_id": 2.5}, "not an integer"),
    ],
)
def test_a_message_breaking_the_contract_is_rejected_with_its_reason(change, reason):
    message = json.loads(encode("2025-06", 1, ROW)[1])
    message.update(change)
    with pytest.raises(Rejected, match=reason):
        decode(json.dumps(message).encode())


def test_business_quality_is_not_a_contract_breach():
    """A negative total is a valid message: the quality flags judge it later."""
    _, value = encode("2025-06", 7, {**ROW, "total_amount": -5.0, "trip_distance": 0.0})
    assert decode(value).total_amount == -5.0


class Message:
    def __init__(self, value, partition=0, offset=0, error=None):
        self._value, self._partition, self._offset, self._error = value, partition, offset, error

    def value(self):
        return self._value

    def partition(self):
        return self._partition

    def offset(self):
        return self._offset

    def error(self):
        return self._error


def test_a_batch_is_split_into_rows_and_rejects_without_stopping():
    good = Message(encode("2025-06", 1, ROW)[1], partition=2, offset=40)
    bad = Message(b"{not json", partition=1, offset=7)
    rows, rejects = split([good, bad])
    assert len(rows) == 1 and rows[0][-2:] == (2, 40)  # the Kafka position is kept
    assert rows[0][0] == date(2025, 6, 1) and rows[0][1] == 1
    assert rejects[0][1:3] == (1, 7) and rejects[0][3].startswith("not JSON")
