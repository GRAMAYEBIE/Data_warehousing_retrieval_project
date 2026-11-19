"""Is the plan grounded in the question? Deterministic checks after the model's plan.

Observed with retrieval on (evaluation of 19 November 2026): a 3B model copies values from
the examples it is shown ("tip rate in Brooklyn last month" planned with the filter
payment_type = Cash of an example, without Brooklyn, for the latest month). Three rules:

1. A period the question names without ambiguity is applied by code: "last month" is the
   previous complete month, "March 2023" is 2023-03 (the platform's fixed definitions).
2. A filter value that is not named in the question, the previous plan or the active
   filters is removed and reported (it was not asked for).
3. A borough or zone named in the question but absent from the plan is a repairable
   rejection: the model gets one corrected plan with the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from assistant.catalog import DIMENSIONS, Catalog
from assistant.retrieval import link_values
from assistant.schemas import DateRange, Filter, Operator, Period, QueryPlan

MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],  # fmt: skip
        start=1,
    )
    for name in names
}
RELATIVE = [
    (r"\b(last|previous|prior) month\b", Period.previous_month),
    (r"\b(this|current|latest) month\b", Period.latest_month),
    (r"\b(last|past|previous) (3|three) months\b", Period.last_3_months),
]
NEGATION = r"\b(not|no|except|excluding|exclude|without|other than|outside|apart from|but not)\b"
# Words that name a measure of the catalogue (a follow-up without them keeps the measures
# of the previous question).
METRIC_WORDS = (
    r"\b(trips?|rides?|revenue|fares?|tips?|distance|duration|miles?|active hour|airport|"
    r"congestion|fee|valid|quality|co2|emissions?|demand|volume|busy)\b"
)
# Named locations must appear in the plan; other named values (payment type, day type...)
# are often context rather than a filter ("tip rate (card trips)"), so they are not forced.
REQUIRED_WHEN_NAMED = {"pickup_borough", "pickup_zone"}


@dataclass
class Grounding:
    plan: QueryPlan
    notes: list[str] = field(default_factory=list)  # adjustments made by code
    missing: list[str] = field(default_factory=list)  # repairable problems


def named_period(question: str) -> DateRange | None:
    text = question.lower()
    found = re.findall(r"\b([a-z]+)\s+(20\d\d)\b", text) + [
        (m, y) for y, m in re.findall(r"\b(20\d\d)-(0[1-9]|1[0-2])\b", text)
    ]
    months = sorted(
        {
            f"{year}-{MONTHS[m]:02d}" if m in MONTHS else f"{year}-{m}"
            for m, year in found
            if m in MONTHS or m.isdigit()
        }
    )
    if months:
        return DateRange(period=Period.custom, start_month=months[0], end_month=months[-1])
    for pattern, period in RELATIVE:
        if re.search(pattern, text):
            return DateRange(period=period)
    return None


def names_a_metric(question: str) -> bool:
    return re.search(METRIC_WORDS, question.lower()) is not None


def ground(
    plan: QueryPlan,
    question: str,
    catalog: Catalog,
    context: list[Filter],
    previous: QueryPlan | None = None,
) -> Grounding:
    """`context`: filters of the previous plan and active filters (a follow-up keeps them);
    `previous`: the previous plan of the conversation, if any."""
    result = Grounding(plan.model_copy(deep=True))
    named = link_values(question, catalog)
    named_values = {link.value.lower() for link in named}
    context_values = {str(v).lower() for f in context for v in f.values}

    period = named_period(question)
    if period and result.plan.date_range != period:
        planned = result.plan.date_range.model_dump(mode="json", exclude_none=True)
        result.notes.append(
            f"period set from the question: {period.model_dump(mode='json', exclude_none=True)} "
            f"(the model planned {planned})"
        )
        result.plan.date_range = period

    # A follow-up that names no measure and no period keeps those of the previous plan
    # ("And for Queens?"). Observed: new measures invented on such a follow-up.
    if previous is not None:
        if (
            not names_a_metric(question)
            and previous.metrics
            and (result.plan.metrics != previous.metrics)
        ):
            result.notes.append(
                f"measures kept from the previous question: {', '.join(previous.metrics)} "
                f"(the model planned {', '.join(result.plan.metrics) or 'none'})"
            )
            result.plan.metrics = list(previous.metrics)
        if period is None and result.plan.date_range != previous.date_range:
            result.notes.append(
                "period kept from the previous question: "
                f"{previous.date_range.model_dump(mode='json', exclude_none=True)}"
            )
            result.plan.date_range = previous.date_range.model_copy()

    # An exclusion needs words of exclusion. Observed: "tip rate in Brooklyn" planned as
    # Brooklyn = and Brooklyn != at the same time.
    excludes = re.search(NEGATION, question.lower()) is not None
    context_exclusions = {
        (f.dimension, str(v).lower())
        for f in context
        if f.operator in (Operator.neq, Operator.not_in)
        for v in f.values
    }

    # A follow-up that names a value replaces the previous value of that dimension ("and for
    # Queens?" after Brooklyn), unless it says it adds ("also", "both", "versus"). Observed:
    # the plan kept Brooklyn and added Queens.
    adds = re.search(r"\b(also|as well|too|both|in addition|including|versus|vs|compared)\b",
                     question.lower())  # fmt: skip
    named_by_dimension: dict[str, set[str]] = {}
    for link in named:
        named_by_dimension.setdefault(link.dimension, set()).add(link.value.lower())

    kept = []
    for f in result.plan.filters:
        categorical = f.dimension in DIMENSIONS and DIMENSIONS[f.dimension].categorical
        if not categorical:  # hours and flags are not linked by name: kept as planned
            kept.append(f)
            continue
        if f.operator in (Operator.neq, Operator.not_in) and not excludes:
            inherited = [v for v in f.values if (f.dimension, str(v).lower()) in context_exclusions]
            if len(inherited) < len(f.values):
                result.notes.append(
                    f"exclusion removed, the question excludes nothing: {f.dimension} "
                    f"{f.operator.value} {', '.join(map(str, f.values))}"
                )
            if inherited:
                kept.append(Filter(dimension=f.dimension, operator=f.operator, values=inherited))
            continue
        allowed = named_values | context_values
        if f.dimension in named_by_dimension and not adds:
            allowed = named_by_dimension[f.dimension]  # replaced by what the question names
        values = [v for v in f.values if str(v).lower() in allowed]
        dropped = [v for v in f.values if v not in values]
        if dropped:
            result.notes.append(
                f"filter removed, not named in the question: {f.dimension} = "
                + ", ".join(map(str, dropped))
            )
        if values:
            kept.append(Filter(dimension=f.dimension, operator=f.operator, values=values))
    result.plan.filters = kept

    planned = {str(v).lower() for f in kept for v in f.values}
    for link in named:
        if link.dimension in REQUIRED_WHEN_NAMED and link.value.lower() not in planned:
            result.missing.append(
                f"not grounded: the question names {link.value!r} ({link.dimension}) "
                "but the plan does not filter on it"
            )
    return result
