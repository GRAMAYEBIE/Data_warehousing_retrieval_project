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
    # Magnitudes are compared: a change is written without its sign ("down 3.2 %" for
    # -3.16), the direction being carried by the words.
    number = abs(number)
    for v in map(abs, candidates):
        if v == number:
            return True
        # Rounding to 3 significant digits, or to one decimal ("-3.2 %" for -3.16, observed
        # rejected while it is an honest rounding).
        tolerance = max(abs(v) * 0.006, 0.0501)
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


DATA_WORDS = re.compile(
    r"\b(trips?|rides?|revenue|fares?|tips?|passengers?|taxis?|cabs?|pickups?|dropoffs?|"
    r"surcharges?|fees?|miles?|distance|duration)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def scrub_data_figures(text: str) -> tuple[str, int]:
    """A conversational answer may not state figures of the taxi data: only governed
    queries produce them. A sentence that pairs a number (other than a year, a day or a
    small count) with a data word is removed. Returns the text and how many sentences were
    removed."""
    kept, removed = [], 0
    for line in text.split("\n"):
        sentences = [s for s in SENTENCE.split(line) if s]
        out = []
        for sentence in sentences:
            numbers = [
                n
                for n in _numbers_in(sentence)
                if not (abs(n) < 32 and float(n).is_integer())
                and not (1990 <= n <= 2100 and float(n).is_integer())
            ]
            if numbers and DATA_WORDS.search(sentence):
                removed += 1
                continue
            out.append(sentence)
        if out or not sentences:
            kept.append(" ".join(out))
    return "\n".join(kept).strip(), removed


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
    """A factual summary, in sentences, that quotes the result only (used when the model's
    text is not trusted). `period` is "April 2025" or "April 2025 compared with March 2025";
    `filters` is "" or " (pickup borough: Manhattan)"."""
    if not rows:
        return f"No trips match this question for {period}{filters}."
    current, _, previous = period.partition(" compared with ")
    metric_columns = {c for m in metrics for c in columns if c == m or c.startswith(f"{m}_")}
    dims = [c for c in columns if c not in metric_columns and c != "period_role"]
    first, meta = next(iter(metrics.items()))

    def cell(row: list, column: str):
        return row[columns.index(column)] if column in columns else None

    def change_of(row: list, name: str) -> float | None:
        pct = cell(row, f"{name}_change_pct")
        if pct is not None:
            return float(pct)
        now, before = cell(row, f"{name}_current"), cell(row, f"{name}_previous")
        if now is None or before in (None, 0):
            return None
        return (float(now) - float(before)) / abs(float(before)) * 100

    def member(row: list) -> str:
        return ", ".join(str(cell(row, d)) for d in dims if d != "period")

    if f"{first}_current" in columns:
        if not dims:
            sentences = []
            for name, m in metrics.items():
                now, before = cell(rows[0], f"{name}_current"), cell(rows[0], f"{name}_previous")
                if now is None:
                    continue
                change = change_of(rows[0], name)
                trend = (
                    "unchanged"
                    if change is None or round(change, 1) == 0
                    else f"{'up' if change > 0 else 'down'} {abs(change):.1f} %"
                )
                sentences.append(
                    f"{m['label']} was {format_value(now, m['unit'])} in {current}, {trend} from "
                    f"{format_value(before, m['unit'])} in {previous or 'the previous period'}."
                )
            return " ".join(sentences) + (f" Filters: {filters.strip(' ()')}." if filters else "")
        items = []
        for row in rows[:5]:
            change = change_of(row, first)
            shown = format_value(cell(row, f"{first}_current"), meta["unit"])
            items.append(
                f"{member(row)} {shown}" + (f" ({change:+.1f} %)" if change is not None else "")
            )
        more = f", and {len(rows) - 5} more in the table" if len(rows) > 5 else ""
        return (
            f"{meta['label']} in {current} versus {previous or 'the previous period'}{filters}: "
            + "; ".join(items)
            + more
            + "."
        )

    if "period" in columns and first in columns and len(rows) > 1:
        points = [
            (str(cell(r, "period"))[:10], cell(r, first))
            for r in rows
            if cell(r, first) is not None
        ]
        low, high = min(points, key=lambda p: float(p[1])), max(points, key=lambda p: float(p[1]))
        return (
            f"{meta['label']} for {period}{filters}, over {len(points)} points: highest "
            f"{format_value(high[1], meta['unit'])} ({high[0]}), lowest "
            f"{format_value(low[1], meta['unit'])} ({low[0]}), latest "
            f"{format_value(points[-1][1], meta['unit'])} ({points[-1][0]})."
        )

    if len(rows) == 1 and not dims:
        parts = [
            f"{m['label']} {format_value(cell(rows[0], name), m['unit'])}"
            for name, m in metrics.items()
            if name in columns
        ]
        return f"{'; '.join(parts)} in {period}{filters}."

    items = [
        f"{member(row) or 'total'} {format_value(cell(row, first), meta['unit'])}"
        for row in rows[:5]
    ]
    more = f", and {len(rows) - 5} more in the table" if len(rows) > 5 else ""
    return f"{meta['label']} in {period}{filters}: " + "; ".join(items) + more + "."
