"""Build the SQL of a validated plan from templates, then check it with SQLGlot.

The LLM never writes SQL. Identifiers come from the allow-lists (catalog relations,
dimensions, metric expressions copied from the dbt YAML); user values are bound
parameters. The rendered SQL must parse as one SELECT that reads `analytics` tables only
and carries a LIMIT, otherwise it is not executed.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from assistant.catalog import DIMENSIONS, GRAIN_SQL, RELATIONS, Catalog
from assistant.schemas import Intent, Operator
from assistant.validator import ResolvedPlan

ALLOWED_SCHEMA = "analytics"


class UnsafeSQL(Exception):
    pass


@dataclass
class BuiltQuery:
    sql: str
    params: dict
    columns: list[str]
    kind: str  # plain | compare


def _month_column(relation: str) -> str:
    return "a.pickup_month" if relation == "routes" else "a.month_start"


def build(resolved: ResolvedPlan, catalog: Catalog, max_rows: int) -> BuiltQuery:
    plan, rel = resolved.plan, resolved.relation
    spec = RELATIONS[rel]
    params: dict = {}
    select, group = [], []

    if plan.intent == Intent.trend:
        grain = plan.grain or "month"
        if grain == "hour":
            select.append("a.pickup_hour AS pickup_hour")
            group.append("a.pickup_hour")
        else:
            col = "a.pickup_month" if rel == "routes" else GRAIN_SQL[grain]
            select.append(f"{col} AS period")
            group.append(col)
    for name in plan.dimensions:
        expr = DIMENSIONS[name].sql[rel]
        select.append(f"{expr} AS {name}")
        group.append(expr)

    months = resolved.months + resolved.comparison_months
    params["months"] = [f"{m}-01" for m in months]
    where = [spec["where"], f"{_month_column(rel)} = ANY(%(months)s::date[])"]
    for i, f in enumerate(resolved.filters):
        expr = DIMENSIONS[f.dimension].sql[rel]
        key = f"f{i}"
        values = [str(v) for v in f.values]
        params[key] = values
        cast = "::text" if DIMENSIONS[f.dimension].categorical else "::text"
        if f.operator in (Operator.eq, Operator.in_):
            where.append(f"({expr}){cast} = ANY(%({key})s)")
        else:
            where.append(f"NOT (({expr}){cast} = ANY(%({key})s))")

    kind = "plain"
    if resolved.comparison_months:
        kind = "compare"
        params["current"] = [f"{m}-01" for m in resolved.months]
        period = (
            f"CASE WHEN {_month_column(rel)} = ANY(%(current)s::date[]) "
            "THEN 'current' ELSE 'previous' END"
        )
        select.append(f"{period} AS period_role")
        group.append(period)

    for metric in plan.metrics:
        select.append(f"{catalog.metrics[metric]['sql_expression']} AS {metric}")

    limit = max_rows if kind == "compare" or plan.intent == Intent.trend else plan.limit
    order = ""
    if kind == "plain" and plan.intent != Intent.trend and plan.metrics:
        direction = "ASC" if plan.order in ("asc", "change_asc") else "DESC"
        order = f"ORDER BY {plan.metrics[0]} {direction} NULLS LAST"
    elif plan.intent == Intent.trend:
        order = "ORDER BY 1"
    sql = (
        f"SELECT {', '.join(select)}\nFROM {spec['from']}\nWHERE {' AND '.join(where)}"
        + (f"\nGROUP BY {', '.join(group)}" if group else "")
        + (f"\n{order}" if order else "")
        + f"\nLIMIT {min(limit, max_rows)}"
    )
    columns = [s.rsplit(" AS ", 1)[1] for s in select]
    check(sql, max_rows)
    return BuiltQuery(sql, params, columns, kind)


def check(sql: str, max_rows: int) -> None:
    """SQLGlot guard: one SELECT, analytics tables only, a LIMIT no larger than allowed."""
    probe = sql.replace("%(", "__p_").replace(")s", "__")  # placeholders parse as names
    try:
        statements = sqlglot.parse(probe, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise UnsafeSQL(f"SQL does not parse: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise UnsafeSQL("only a single SELECT statement is allowed")
    tree = statements[0]
    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
        exp.Merge,
        exp.TruncateTable,
    )
    if any(tree.find(node) for node in forbidden):
        raise UnsafeSQL("data-changing statement detected")
    for table in tree.find_all(exp.Table):
        if not table.name:  # lateral or derived table
            continue
        if table.db != ALLOWED_SCHEMA:
            raise UnsafeSQL(f"table {table.sql()} is outside the {ALLOWED_SCHEMA} schema")
    limit = tree.args.get("limit")
    if limit is None:
        raise UnsafeSQL("a LIMIT is required")
    value = limit.expression
    if not isinstance(value, exp.Literal) or int(value.this) > max_rows:
        raise UnsafeSQL(f"LIMIT must be a number at most {max_rows}")


def render(sql: str, params: dict) -> str:
    """SQL with parameters shown inline, for provenance and the audit log only."""
    shown = sql
    for key, value in params.items():
        literal = "ARRAY[" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in value) + "]"
        shown = shown.replace(f"%({key})s", literal)
    return shown


def pivot_comparison(
    columns: list[str],
    rows: list[tuple],
    dims: list[str],
    metrics: list[str],
    order: str,
    limit: int,
) -> tuple[list[str], list[list]]:
    """current versus previous period, per dimension member, with change and % change."""
    by_key: dict[tuple, dict] = {}
    role_idx = columns.index("period_role")
    for row in rows:
        key = tuple(row[columns.index(d)] for d in dims)
        entry = by_key.setdefault(key, {})
        for m in metrics:
            entry[(row[role_idx], m)] = row[columns.index(m)]
    out_cols = list(dims)
    for m in metrics:
        out_cols += [f"{m}_previous", f"{m}_current", f"{m}_change", f"{m}_change_pct"]
    out_rows = []
    for key, entry in by_key.items():
        line = list(key)
        for m in metrics:
            prev, cur = entry.get(("previous", m)), entry.get(("current", m))
            change = None if prev is None or cur is None else cur - prev
            pct = (
                None if change is None or not prev else round(100 * float(change) / float(prev), 2)
            )
            line += [prev, cur, change, pct]
        out_rows.append(line)
    first = f"{metrics[0]}_change"
    idx = out_cols.index(first)
    descending = order in ("desc", "change_desc")
    out_rows.sort(key=lambda r: (r[idx] is None, -(r[idx] or 0) if descending else (r[idx] or 0)))
    return out_cols, out_rows[:limit]
