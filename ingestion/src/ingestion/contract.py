"""Source contract: expected columns, schema hash and schema-drift detection."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pyarrow as pa
import yaml


def _is_number(t: pa.DataType) -> bool:
    return pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_decimal(t)


def _is_string(t: pa.DataType) -> bool:
    return pa.types.is_string(t) or pa.types.is_large_string(t)


FAMILIES = {
    "integer": pa.types.is_integer,
    "number": _is_number,
    "timestamp": pa.types.is_timestamp,
    "string": _is_string,
}


@dataclass(frozen=True)
class ContractColumn:
    name: str
    family: str
    required: bool = True


@dataclass(frozen=True)
class Contract:
    dataset: str
    version: str
    valid_from: str  # "YYYY-MM"
    columns: tuple[ContractColumn, ...]

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


@dataclass
class DriftReport:
    """Difference between a file schema and its contract."""

    unknown_columns: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    type_mismatches: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        """A missing required column or a wrong type family stops the load."""
        return bool(self.missing_required or self.type_mismatches)

    @property
    def has_drift(self) -> bool:
        return bool(
            self.unknown_columns
            or self.missing_required
            or self.missing_optional
            or self.type_mismatches
        )

    def to_dict(self) -> dict:
        return asdict(self)


def normalise(name: str) -> str:
    """Source column names vary in case between files (Airport_fee / airport_fee)."""
    return name.strip().lower()


def load_contract(contracts_dir: Path, dataset: str, month: str) -> Contract:
    """Pick the contract version whose valid_from is the latest one <= month ("YYYY-MM")."""
    candidates: list[Contract] = []
    for path in sorted(contracts_dir.glob(f"{dataset}_*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        contract = Contract(
            dataset=raw["dataset"],
            version=raw["version"],
            valid_from=str(raw["valid_from"]),
            columns=tuple(ContractColumn(**c) for c in raw["columns"]),
        )
        for col in contract.columns:
            if col.family not in FAMILIES:
                raise ValueError(f"{path.name}: unknown family {col.family!r} for {col.name}")
        if contract.valid_from <= month:
            candidates.append(contract)
    if not candidates:
        raise LookupError(f"No {dataset} contract covers {month} in {contracts_dir}")
    return max(candidates, key=lambda c: c.valid_from)


def schema_hash(schema: pa.Schema) -> str:
    """SHA-256 of the sorted 'name:type' list. Changes whenever a column or a type changes."""
    parts = sorted(f"{normalise(f.name)}:{f.type}" for f in schema)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def check_schema(schema: pa.Schema, contract: Contract) -> DriftReport:
    """Compare a file schema to the contract and report every difference."""
    report = DriftReport()
    actual = {normalise(f.name): f.type for f in schema}
    expected = {c.name: c for c in contract.columns}

    for name, col in expected.items():
        if name not in actual:
            (report.missing_required if col.required else report.missing_optional).append(name)
        elif not FAMILIES[col.family](actual[name]):
            report.type_mismatches.append(f"{name}: expected {col.family}, got {actual[name]}")

    report.unknown_columns = sorted(n for n in actual if n not in expected)
    return report
