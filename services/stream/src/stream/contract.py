"""The message contract of the topic trips.yellow.raw (schema yellow_trip/v1).

One message per trip, JSON, keyed by the pickup zone (so a zone's trips stay in order on one
partition). The producer builds it from a row of the monthly file; the consumer checks it
before writing anything. A message that breaks the contract is not dropped silently: it
goes to the dead-letter topic and to stream.yellow_trips_rejects with the reason.

The contract checks structure, not business quality: a negative total or a zero distance
is a valid message (the quality flags of the batch path judge it later, and the live view
applies the same plausibility rules when it reads). A message is rejected when it cannot be
stored or read at all: unknown schema, missing field, wrong type, impossible value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

SCHEMA = "yellow_trip/v1"
TOPIC = "trips.yellow.raw"
DEAD_LETTERS = "trips.yellow.dlq"

# Field of the message -> column of the monthly file.
FIELDS = {
    "vendor_id": "VendorID",
    "pickup": "tpep_pickup_datetime",
    "dropoff": "tpep_dropoff_datetime",
    "passengers": "passenger_count",
    "distance": "trip_distance",
    "pu": "PULocationID",
    "do": "DOLocationID",
    "payment": "payment_type",
    "fare": "fare_amount",
    "tip": "tip_amount",
    "total": "total_amount",
}
REQUIRED = ("source_month", "row", "pickup", "dropoff", "pu", "do", "distance", "total")
ZONES = range(1, 266)  # TLC location ids (264 and 265: unknown)


class Rejected(ValueError):
    """The message breaks the contract; the text says why."""


@dataclass(frozen=True)
class Trip:
    source_month: date
    file_row_number: int
    vendor_id: int | None
    pickup_ts: datetime
    dropoff_ts: datetime
    pu_location_id: int
    do_location_id: int
    passenger_count: int | None
    trip_distance: float
    payment_type: int | None
    fare_amount: float | None
    tip_amount: float | None
    total_amount: float


def _number(value):
    """None for a missing value or NaN (the monthly files carry both)."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    return value


def encode(source_month: str, row_number: int, row: dict) -> tuple[bytes, bytes]:
    """(key, value) of the message for one row of the monthly file."""
    message = {"schema": SCHEMA, "source_month": source_month, "row": row_number}
    for field, column in FIELDS.items():
        value = _number(row.get(column))
        if isinstance(value, datetime):
            value = value.isoformat()
        message[field] = value
    key = str(message.get("pu") or 0).encode()
    return key, json.dumps(message, separators=(",", ":")).encode()


def _int(message: dict, field: str, optional: bool = True) -> int | None:
    value = message.get(field)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise Rejected(f"{field} is not an integer: {value!r}")
    return int(value)


def _float(message: dict, field: str, optional: bool = True) -> float | None:
    value = message.get(field)
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Rejected(f"{field} is not a number: {value!r}")
    return float(value)


def decode(payload: bytes) -> Trip:
    """The trip of a message, or Rejected with the reason."""
    try:
        message = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejected(f"not JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise Rejected("not a JSON object")
    if message.get("schema") != SCHEMA:
        raise Rejected(f"unknown schema {message.get('schema')!r}, expected {SCHEMA}")
    missing = [f for f in REQUIRED if message.get(f) is None]
    if missing:
        raise Rejected(f"missing field(s): {', '.join(missing)}")
    try:
        month = date.fromisoformat(f"{message['source_month']}-01")
        pickup = datetime.fromisoformat(message["pickup"])
        dropoff = datetime.fromisoformat(message["dropoff"])
    except (TypeError, ValueError) as exc:
        raise Rejected(f"bad date: {exc}") from exc
    pu, do = _int(message, "pu", False), _int(message, "do", False)
    if pu not in ZONES or do not in ZONES:
        raise Rejected(f"unknown zone: pickup {pu}, dropoff {do}")
    distance, total = _float(message, "distance", False), _float(message, "total", False)
    if not -1e5 < total < 1e5 or not 0 <= distance < 1e5:
        raise Rejected(f"impossible value: distance {distance}, total {total}")
    row = _int(message, "row", False)
    if row < 0:
        raise Rejected(f"negative row number {row}")
    return Trip(
        source_month=month,
        file_row_number=row,
        vendor_id=_int(message, "vendor_id"),
        pickup_ts=pickup,
        dropoff_ts=dropoff,
        pu_location_id=pu,
        do_location_id=do,
        passenger_count=_int(message, "passengers"),
        trip_distance=distance,
        payment_type=_int(message, "payment"),
        fare_amount=_float(message, "fare"),
        tip_amount=_float(message, "tip"),
        total_amount=total,
    )
