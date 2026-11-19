"""Deterministic guardrails around the language model.

Before the model: questions about topics the data cannot answer, or carrying injection
attempts, are stopped by rules that do not depend on the model's behaviour.
After the model: every number in the narrative must come from the query result. When a
number cannot be traced to a result value, the narrative is replaced by a deterministic
summary built from the result itself.
"""

from __future__ import annotations

import re
from decimal import Decimal

from assistant.catalog import INJECTION_PATTERNS, UNSUPPORTED_TOPICS

NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|million|m\b|k\b|bn\b)?", re.IGNORECASE
)


def unsupported_reason(question: str) -> str | None:
    text = question.lower()
    for pattern, reason in UNSUPPORTED_TOPICS.items():
        if re.search(pattern, text):
            return reason
    return None


def injection_detected(question: str) -> bool:
    text = question.lower()
    return any(re.search(p, text) for p in INJECTION_PATTERNS)


def _numbers_in(text: str) -> list[float]:
    values = []
    for match in NUMBER.finditer(text):
        token = match.group(0).lower().replace(",", "").strip()
        scale = 1.0
        for suffix, factor in (("million", 1e6), ("bn", 1e9), ("m", 1e6), ("k", 1e3)):
            if token.endswith(suffix):
                token, scale = token[: -len(suffix)].strip(), factor
                break
        token = token.replace("percent", "").replace("%", "").strip()
        try:
            values.append(float(token) * scale)
        except ValueError:
            continue
    return values


def _result_values(rows: list[list]) -> list[float]:
    values = []
    for row in rows:
        for cell in row:
            if isinstance(cell, bool) or cell is None:
                continue
            if isinstance(cell, (int, float, Decimal)):
                v = float(cell)
                values += [v, v * 100]  # ratios are quoted as percentages
            else:
                values += _numbers_in(str(cell))  # e.g. dates, zone names with numbers
    return values


def _matches(number: float, candidates: list[float]) -> bool:
    for v in candidates:
        if v == number:
            return True
        tolerance = max(abs(v) * 0.006, 0.006)  # rounding to 3 significant digits or 2 decimals
        if abs(v - number) <= tolerance:
            return True
    return False


def unsupported_numbers(
    narrative: str, rows: list[list], allowed: list[float] | None = None
) -> list[float]:
    """Numbers of the narrative that cannot be traced to the result."""
    candidates = _result_values(rows) + (allowed or [])
    found = []
    for n in _numbers_in(narrative):
        if abs(n) < 32 and float(n).is_integer():
            continue  # day numbers, small counts such as "top 5", ordinal words
        if 1990 <= n <= 2100 and float(n).is_integer():
            continue  # years
        if not _matches(n, candidates):
            found.append(n)
    return found


HIGH_WORDS = ("highest", "most", "largest", "biggest", "top", "leading", "led ", "greatest")
LOW_WORDS = ("lowest", "least", "smallest", "fewest", "bottom", "weakest")


def wrong_rankings(narrative: str, columns: list[str], rows: list[list], metric: str) -> list[str]:
    """Superlative claims about a member that the result contradicts.

    The number check cannot see them: "Brooklyn had the lowest revenue at $1.85 million"
    quotes a true number but is false when the Bronx is lower (observed on the first real
    test). In each sentence with a superlative and exactly one member of the first
    dimension, that member must be the maximum (or the minimum) of the metric.
    """
    dims = [c for c in columns if c != metric and not c.startswith(metric)]
    if metric not in columns or not dims or len(rows) < 2:
        return []
    m, d = columns.index(metric), columns.index(dims[0])
    values = {str(r[d]): float(r[m]) for r in rows if r[m] is not None}
    if len(values) < 2:
        return []
    highest, lowest = max(values, key=values.get), min(values, key=values.get)
    problems = []
    for sentence in re.split(r"(?<=[.!?;])\s+", narrative):
        text = sentence.lower()
        named = [name for name in values if re.search(rf"\b{re.escape(name.lower())}\b", text)]
        if len(named) != 1:
            continue  # several members in one sentence: the claim is not attributable
        name = named[0]
        if any(w in text for w in LOW_WORDS) and name != lowest:
            problems.append(f"'{name}' called lowest, but the lowest is '{lowest}'")
        elif any(w in text for w in HIGH_WORDS) and name != highest:
            problems.append(f"'{name}' called highest, but the highest is '{highest}'")
    return problems


def format_value(value, unit: str) -> str:
    if value is None:
        return "no value"
    v = float(value)
    if unit == "ratio":
        return f"{v * 100:.1f} %"
    if unit.startswith("USD"):
        return f"{v:,.2f} USD" if abs(v) < 1000 else f"{v:,.0f} USD"
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def deterministic_summary(
    columns: list[str], rows: list[list], metrics: dict[str, dict], period: str, filters: str
) -> str:
    """A factual summary that quotes the result only (used when the model is not trusted)."""
    if not rows:
        return f"No data matches this question for {period}{filters}."
    lines = [f"Result for {period}{filters}:"]
    dims = [c for c in columns if c not in metrics and not any(c.startswith(m) for m in metrics)]
    for row in rows[:5]:
        label = ", ".join(str(row[columns.index(d)]) for d in dims) or "total"
        parts = []
        for name, meta in metrics.items():
            for col in (name, f"{name}_current", f"{name}_change_pct"):
                if col in columns:
                    value = row[columns.index(col)]
                    shown = (
                        f"{value} %"
                        if col.endswith("_pct") and value is not None
                        else format_value(value, meta["unit"])
                    )
                    parts.append(
                        f"{meta['label']}{' change' if col.endswith('_pct') else ''} {shown}"
                    )
        lines.append(f"- {label}: " + "; ".join(parts))
    if len(rows) > 5:
        lines.append(f"({len(rows) - 5} more rows in the table.)")
    return "\n".join(lines)
