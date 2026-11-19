"""Targeted retrieval for the planner: retrieval-augmented planning, never retrieved numbers.

Two retrievals are added to the planner's user message (the cached system prompt does not
change):

1. Values named in the question, linked to the governed vocabulary: "Manhatan" -> Manhattan
   (pickup_borough), "JFK" -> JFK Airport (pickup_zone), "card" -> Credit card. The model
   then copies exact spellings instead of guessing, and is told when the question names no
   value, so it does not invent filters (observed in the baseline evaluation: boroughs used
   as zone filters on a question that named none).
2. The validated example plans closest to the question (weighted word overlap), so a small
   model sees two or three correct plans of the same kind.

Numbers always come from the governed SQL, never from retrieved text.
"""

from __future__ import annotations

import difflib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from assistant.catalog import Catalog

EXAMPLES = Path(__file__).resolve().parents[1] / "prompts" / "plan_examples.yaml"

# Words that name a value without spelling it (checked before exact member names).
ALIASES: dict[str, tuple[str, str]] = {
    "jfk": ("pickup_zone", "JFK Airport"),
    "kennedy": ("pickup_zone", "JFK Airport"),
    "laguardia": ("pickup_zone", "LaGuardia Airport"),
    "la guardia": ("pickup_zone", "LaGuardia Airport"),
    "lga": ("pickup_zone", "LaGuardia Airport"),
    "newark": ("pickup_zone", "Newark Airport"),
    "credit card": ("payment_type", "Credit card"),
    "card": ("payment_type", "Credit card"),
    "cash": ("payment_type", "Cash"),
    "holiday": ("day_type", "Public holiday"),
    "holidays": ("day_type", "Public holiday"),
    "weekend": ("day_type", "Weekend"),
    "weekends": ("day_type", "Weekend"),
    "weekday": ("day_type", "Weekday"),
    "weekdays": ("day_type", "Weekday"),
    "morning peak": ("service_period", "AM peak"),
    "evening peak": ("service_period", "PM peak"),
    "late night": ("service_period", "Late night"),
}
# Dimensions whose values a question names in plain words.
LINKED = [
    "pickup_borough",
    "pickup_zone",
    "pickup_market_segment",
    "payment_type",
    "vendor",
    "day_type",
    "day_of_week",
    "service_period",
]
# Typo tolerance only for names (boroughs, zones), not for short codes.
FUZZY = {"pickup_borough", "pickup_zone"}
GENERIC = {"unknown", "not reported", "other"}
# Words that carry no information for matching names or examples.
STOP = {
    "a", "an", "the", "of", "in", "on", "at", "by", "for", "to", "and", "or", "is", "are",
    "was", "were", "what", "which", "how", "many", "much", "did", "do", "does", "show", "me",
    "give", "with", "from", "than", "this", "that", "last", "month", "week", "day", "our",
    "we",
}  # fmt: skip


@dataclass(frozen=True)
class Link:
    dimension: str
    value: str
    matched: str  # the words of the question that named it


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text) is not None


def link_values(question: str, catalog: Catalog) -> list[Link]:
    """Values of the governed vocabulary named in the question (exact, alias or typo)."""
    text = question.lower()
    links: dict[tuple[str, str], Link] = {}
    for alias, (dim, value) in ALIASES.items():
        if _has_phrase(text, alias) and value in catalog.members.get(dim, []):
            links[(dim, value)] = Link(dim, value, alias)
    for dim in LINKED:
        for member in catalog.members.get(dim, []):
            name = member.lower()
            if name in GENERIC or len(name) < 3 or any(k[1] == member for k in links):
                continue
            if _has_phrase(text, name):
                links[(dim, member)] = Link(dim, member, name)
    # Typos on names: compare word groups of the question with borough and zone names.
    words = [w for w in _words(question) if w not in STOP]
    grams = {" ".join(words[i : i + n]) for n in (1, 2, 3) for i in range(len(words) - n + 1)}
    for dim in FUZZY:
        found = {k[1] for k in links if k[0] == dim}
        names = {m.lower(): m for m in catalog.members.get(dim, []) if m.lower() not in GENERIC}
        for gram in grams:
            if len(gram) < 5:
                continue
            close = difflib.get_close_matches(gram, list(names), n=1, cutoff=0.88)
            if close and names[close[0]] not in found and close[0] != gram:
                links[(dim, names[close[0]])] = Link(dim, names[close[0]], gram)
    # A borough name inside a longer zone name ("Manhattan Valley") is not the borough.
    zones = [link.value.lower() for link in links.values() if link.dimension == "pickup_zone"]
    return [
        link
        for link in links.values()
        if not (
            link.dimension == "pickup_borough"
            and any(link.value.lower() in z and link.value.lower() != z for z in zones)
        )
    ]


def describe_links(links: list[Link]) -> str:
    if not links:
        return (
            "VALUES NAMED IN THE QUESTION: none. Do not add a filter unless the previous plan "
            "or the active filters apply."
        )
    lines = ["VALUES NAMED IN THE QUESTION (use these exact spellings in filters):"]
    for link in links:
        note = " (dropoff_borough only if the question is about drop-offs)"
        lines.append(
            f"- {link.dimension} = {link.value!r}, from '{link.matched}'"
            + (note if link.dimension == "pickup_borough" else "")
        )
    return "\n".join(lines)


@lru_cache
def load_examples(path: Path = EXAMPLES) -> tuple[dict, ...]:
    return tuple(yaml.safe_load(path.read_text(encoding="utf-8"))["examples"])


def _idf(examples: tuple[dict, ...]) -> dict[str, float]:
    docs = [set(_words(e["question"])) - STOP for e in examples]
    vocabulary = set().union(*docs)
    return {w: math.log((1 + len(docs)) / (1 + sum(w in d for d in docs))) + 1 for w in vocabulary}


def similar_examples(question: str, k: int = 3) -> list[dict]:
    """The k example plans whose questions share the most informative words."""
    examples = load_examples()
    idf = _idf(examples)
    asked = set(_words(question)) - STOP
    scored = []
    for example in examples:
        words = set(_words(example["question"])) - STOP
        shared = sum(idf.get(w, 0) for w in asked & words)
        norm = math.sqrt(sum(idf.get(w, 0) ** 2 for w in words) or 1)
        if shared:
            scored.append((shared / norm, example))
    return [e for _, e in sorted(scored, key=lambda pair: -pair[0])[:k]]


def describe_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = ["SIMILAR VALIDATED EXAMPLES (question -> plan):"]
    for e in examples:
        lines.append(f'- "{e["question"]}" -> {json.dumps(e["plan"], separators=(",", ":"))}')
    return "\n".join(lines)


def retrieved_context(question: str, catalog: Catalog) -> str:
    """The text added to the planner's user message."""
    parts = [describe_links(link_values(question, catalog))]
    examples = describe_examples(similar_examples(question))
    if examples:
        parts.append(examples)
    return "\n\n".join(parts)
