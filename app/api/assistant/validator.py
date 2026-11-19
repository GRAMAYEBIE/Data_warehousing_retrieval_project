"""Policy validation of a plan: nothing reaches the database unless every part is governed.

Rejects unknown metrics and dimensions, filters on values that do not exist, conflicting
filters, dates outside the published coverage, and combinations no published table can
compute. Resolves relative periods ("latest_month") to concrete months.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from assistant.catalog import DIMENSIONS, RELATIONS, Catalog
from assistant.schemas import Filter, Intent, Operator, Period, QueryPlan


class PlanRejected(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons

    @property
    def repairable(self) -> bool:
        """True when every reason is a vocabulary mistake of the model (an unknown metric,
        dimension or filter value, a combination no table holds), which one re-plan with
        the reasons can fix. A date outside the coverage, conflicting filters or a missing
        previous period are real limits of the request: they are explained, never
        "repaired", because repairing them would change what the manager asked."""
        return bool(self.reasons) and all(r.startswith(REPAIRABLE) for r in self.reasons)


REPAIRABLE = (
    "unknown metric",
    "unknown dimension",
    "unknown filter dimension",
    "invalid filter",
    "no metric requested",
    "no published table can compute",
    "not grounded",
)


@dataclass
class ResolvedPlan:
    plan: QueryPlan
    relation: str
    months: list[str]  # months of the main period, 'YYYY-MM'
    comparison_months: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)  # canonical member values


def resolve_months(plan: QueryPlan, coverage: list[str]) -> tuple[list[str], list[str]]:
    """Main and comparison months. 'Latest' means the latest complete published month."""
    if not coverage:
        raise PlanRejected(["no complete month is published yet"])
    dr = plan.date_range
    if dr.period == Period.latest_month:
        main = coverage[-1:]
    elif dr.period == Period.previous_month:
        if len(coverage) < 2:
            raise PlanRejected(["only one complete month is published: no previous month"])
        main = coverage[-2:-1]
    elif dr.period == Period.last_3_months:
        main = coverage[-3:]
    elif dr.period == Period.custom:
        start, end = dr.start_month or coverage[0], dr.end_month or dr.start_month or coverage[-1]
        if start > end:
            raise PlanRejected([f"invalid date range: {start} is after {end}"])
        outside = [m for m in (start, end) if m not in coverage]
        if outside:
            raise PlanRejected(
                [
                    f"unsupported date range: {', '.join(outside)} is not published; "
                    f"complete months available: {coverage[0]} to {coverage[-1]}"
                ]
            )
        main = [m for m in coverage if start <= m <= end]
    else:
        main = list(coverage)

    comparison: list[str] = []
    if plan.compare_to == "previous_period" or plan.intent == Intent.compare:
        first = coverage.index(main[0])
        size = len(main)
        if first - size < 0:
            raise PlanRejected(
                [f"no previous period of {size} month(s) before {main[0]} is published"]
            )
        comparison = coverage[first - size : first]
    return main, comparison


def canonical_filters(filters: list[Filter], catalog: Catalog) -> list[Filter]:
    reasons, result = [], []
    for f in filters:
        if f.dimension not in DIMENSIONS:
            reasons.append(f"unknown filter dimension: {f.dimension}")
            continue
        members = catalog.members.get(f.dimension, [])
        lookup = {m.lower(): m for m in members}
        values = []
        for v in f.values:
            key = str(v).lower()
            if key not in lookup:
                close = [m for m in members if key[:4] and key[:4] in m.lower()][:5]
                hint = f" (did you mean: {', '.join(close)}?)" if close else ""
                reasons.append(f"invalid filter: {f.dimension} has no value '{v}'{hint}")
            else:
                values.append(lookup[key])
        if values:  # when every value is invalid, the reasons above explain it
            result.append(Filter(dimension=f.dimension, operator=f.operator, values=values))
    if reasons:
        raise PlanRejected(reasons)

    # Conflicting filters: two equality filters on one dimension with different values,
    # or a value both included and excluded.
    by_dim: dict[str, dict[str, set]] = {}
    for f in result:
        entry = by_dim.setdefault(f.dimension, {"in": set(), "out": set(), "eq": []})
        if f.operator in (Operator.eq, Operator.in_):
            entry["in"] |= set(f.values)
            entry["eq"].append(set(f.values))
        else:
            entry["out"] |= set(f.values)
    for dim, entry in by_dim.items():
        if len(entry["eq"]) > 1 and not set.intersection(*entry["eq"]):
            reasons.append(f"conflicting filters on {dim}: no row can match all of them")
        if entry["in"] & entry["out"]:
            reasons.append(
                f"conflicting filters on {dim}: "
                f"{', '.join(sorted(map(str, entry['in'] & entry['out'])))} "
                "is both included and excluded"
            )
    if reasons:
        raise PlanRejected(reasons)
    return result


def validate(plan: QueryPlan, catalog: Catalog) -> ResolvedPlan:
    if plan.intent in (Intent.clarify, Intent.unsupported):
        return ResolvedPlan(plan, relation="", months=[])
    reasons = []
    if not plan.metrics:
        reasons.append("no metric requested")
    unknown = [m for m in plan.metrics if m not in catalog.metrics]
    if unknown:
        reasons.append(
            f"unknown metric(s): {', '.join(unknown)}; governed metrics: "
            f"{', '.join(sorted(catalog.metrics))}"
        )
    bad_dims = [d for d in plan.dimensions if d not in DIMENSIONS]
    if bad_dims:
        reasons.append(f"unknown dimension(s): {', '.join(bad_dims)}")
    if reasons:
        raise PlanRejected(reasons)

    filters = canonical_filters(plan.filters, catalog)
    months, comparison = resolve_months(plan, catalog.months)

    # One published table must hold every metric, dimension and filter of the plan.
    needed_dims = set(plan.dimensions) | {f.dimension for f in filters}
    candidates = set(RELATIONS)
    for metric in plan.metrics:
        candidates &= set(catalog.metric_relations(metric))
    for dim in needed_dims:
        candidates &= set(DIMENSIONS[dim].sql)
    if plan.grain == "hour":
        candidates &= {"hourly"}
    if plan.grain in ("day", "week") or plan.intent == Intent.trend and plan.grain != "month":
        candidates -= {"routes"}  # monthly table
    if not candidates:
        raise PlanRejected(
            [
                "no published table can compute "
                f"{', '.join(plan.metrics)} by {', '.join(sorted(needed_dims)) or 'nothing'}"
                + (f" at {plan.grain} grain" if plan.grain else "")
                + ": ask for another breakdown"
            ]
        )
    order = ["daily", "hourly", "routes"]
    preferred = catalog.metric_relations(plan.metrics[0])[0]
    relation = preferred if preferred in candidates else min(candidates, key=order.index)
    return ResolvedPlan(plan, relation, months, comparison, filters)
