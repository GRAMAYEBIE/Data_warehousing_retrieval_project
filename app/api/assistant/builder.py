"""Draft reports and dashboards in Superset (exam Q8).

The model turns the request into a ReportRequest (plans plus chart wishes). Each plan is
validated like a question and run for the preview. Charts and a dashboard are created
through the Superset REST API as a DRAFT (title prefixed with [DRAFT], not published),
by the `ai_builder` service account (Superset role Alpha: it can create charts and
dashboards, it cannot manage users, roles or database connections). Nothing is
published until the manager confirms; replacing an existing dashboard needs a second,
explicit flag.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import httpx

from assistant.catalog import Catalog
from assistant.resolver import build, pivot_comparison, render
from assistant.schemas import Intent, QueryPlan, ReportRequest
from assistant.validator import ResolvedPlan, validate

DATASET_BY_RELATION = {"daily": "trips_daily", "hourly": "trips_hourly", "routes": "routes_monthly"}
COLUMN_BY_DIMENSION = {
    "pickup_borough": "pickup_borough",
    "pickup_zone": "pickup_zone",
    "pickup_market_segment": "pickup_market_segment",
    "dropoff_borough": "dropoff_borough",
    "dropoff_zone": "dropoff_zone",
    "route": "route",
    "payment_type": "payment_type_name",
    "rate_code": "rate_code_name",
    "vendor": "vendor_name",
    "day_type": "day_type",
    "day_of_week": "day_name",
    "pickup_hour": "pickup_hour",
    "service_period": "service_period_name",
    "is_airport_trip": "is_airport_trip",
}
GRAIN = {"day": "P1D", "week": "P1W", "month": "P1M"}
DRAFT_PREFIX = "[DRAFT] "


class BuilderError(Exception):
    pass


@dataclass
class Draft:
    report_id: str
    title: str
    dashboard_id: int
    chart_ids: list[int]
    spec: dict
    preview: list[dict]
    status: str = "draft"
    created_at: float = field(default_factory=time.time)


class SupersetClient:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url
        self.http = httpx.Client(base_url=url, timeout=300)
        login = self.http.post(
            "/api/v1/security/login",
            json={"username": user, "password": password, "provider": "db", "refresh": False},
        )
        if login.status_code != 200:
            raise BuilderError(f"Superset login failed for {user}: HTTP {login.status_code}")
        self.http.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        csrf = self.http.get("/api/v1/security/csrf_token/")
        self.http.headers["X-CSRFToken"] = csrf.json()["result"]
        self.http.headers["Referer"] = url

    def call(self, method: str, path: str, **kwargs) -> dict:
        response = self.http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise BuilderError(
                f"{method} {path}: HTTP {response.status_code} {response.text[:300]}"
            )
        return response.json() if response.content else {}

    def dataset_id(self, name: str) -> int:
        query = {"filters": [{"col": "table_name", "opr": "eq", "value": name}]}
        result = self.call("GET", "/api/v1/dataset/", params={"q": json.dumps(query)})
        if not result.get("result"):
            raise BuilderError(f"certified dataset {name} not found")
        return result["result"][0]["id"]

    def dashboard_by_title(self, title: str) -> dict | None:
        query = {"filters": [{"col": "dashboard_title", "opr": "eq", "value": title}]}
        result = self.call("GET", "/api/v1/dashboard/", params={"q": json.dumps(query)})
        return result["result"][0] if result.get("result") else None


def chart_form_data(resolved: ResolvedPlan, dataset_id: int, kind: str) -> dict:
    plan, rel = resolved.plan, resolved.relation
    month_col = "pickup_month" if rel == "routes" else "month_start"
    months = sorted(resolved.months + resolved.comparison_months)
    filters = [
        {
            "clause": "WHERE",
            "expressionType": "SIMPLE",
            "subject": month_col,
            "operator": "IN",
            "comparator": [f"{m}-01" for m in months],
        }
    ]
    for f in resolved.filters:
        filters.append(
            {
                "clause": "WHERE",
                "expressionType": "SIMPLE",
                "subject": COLUMN_BY_DIMENSION[f.dimension],
                "operator": "NOT IN" if f.operator.value in ("!=", "not in") else "IN",
                "comparator": [str(v) for v in f.values],
            }
        )
    base = {
        "datasource": f"{dataset_id}__table",
        "adhoc_filters": filters,
        "row_limit": 1000,
        "color_scheme": "metromove",
    }
    dims = [COLUMN_BY_DIMENSION[d] for d in plan.dimensions]
    if kind == "big_number":
        return base | {"viz_type": "big_number_total", "metric": plan.metrics[0]}
    if kind == "table":
        return base | {
            "viz_type": "table",
            "query_mode": "aggregate",
            "groupby": dims,
            "metrics": plan.metrics,
            "order_desc": True,
        }
    if kind == "pie":
        return base | {
            "viz_type": "pie",
            "groupby": dims[:1],
            "metric": plan.metrics[0],
            "donut": True,
            "show_labels": True,
        }
    if plan.intent == Intent.trend or kind == "line":
        x = (
            "pickup_hour"
            if plan.grain == "hour"
            else ("pickup_month" if rel == "routes" else "date_day")
        )
        data = base | {
            "viz_type": "echarts_timeseries_line",
            "x_axis": x,
            "metrics": plan.metrics,
            "groupby": dims,
            "rich_tooltip": True,
            "show_legend": True,
            "markerEnabled": True,
        }
        if plan.grain != "hour":
            data["time_grain_sqla"] = GRAIN.get(plan.grain or "month", "P1M")
        return data
    # bar: by dimension, or by month when comparing periods
    x = dims[0] if dims else month_col
    data = base | {
        "viz_type": "echarts_timeseries_bar",
        "x_axis": x,
        "metrics": plan.metrics,
        "groupby": dims[1:] if dims else [],
        "show_value": True,
        "rich_tooltip": True,
    }
    if not dims:  # one bar per month: e.g. this month versus last month
        data["time_grain_sqla"] = "P1M"
    return data


class ReportBuilder:
    def __init__(self, assistant) -> None:
        self.assistant = assistant
        self.drafts: dict[str, Draft] = {}

    def client(self) -> SupersetClient:
        s = self.assistant.settings
        if not s.superset_password:
            raise BuilderError("SUPERSET_AI_PASSWORD is not configured")
        return SupersetClient(s.superset_url, s.superset_user, s.superset_password)

    def _preview(self, resolved: ResolvedPlan, catalog: Catalog) -> dict:
        built = build(resolved, catalog, self.assistant.settings.max_rows)
        columns, rows, _ = self.assistant.store.query(built.sql, built.params)
        rows = [list(r) for r in rows]
        if built.kind == "compare":
            columns, rows = pivot_comparison(
                columns,
                rows,
                resolved.plan.dimensions,
                resolved.plan.metrics,
                resolved.plan.order,
                resolved.plan.limit,
            )
        return {
            "columns": columns,
            "rows": rows[:50],
            "row_count": len(rows),
            "sql": render(built.sql, built.params),
        }

    def draft(self, request: ReportRequest) -> Draft:
        catalog = self.assistant.catalog()
        plans: list[tuple[QueryPlan, str, str]] = [
            (
                QueryPlan.model_validate(
                    request.model_dump(
                        exclude={
                            "chart_recommendation",
                            "dashboard_title",
                            "explanation",
                            "extra_charts",
                        }
                    )
                ),
                request.chart_recommendation,
                request.dashboard_title,
            )
        ]
        for i, extra in enumerate(request.extra_charts, start=1):
            kind = (
                "bar"
                if extra.compare_to == "previous_period" or extra.intent == Intent.compare
                else "line"
            )
            plans.append((extra, kind, f"{request.dashboard_title} - chart {i + 1}"))

        resolved_plans = [(validate(p, catalog), kind, name) for p, kind, name in plans]
        previews = [self._preview(r, catalog) for r, _, _ in resolved_plans]

        api = self.client()
        title = DRAFT_PREFIX + request.dashboard_title
        dashboard = api.call(
            "POST",
            "/api/v1/dashboard/",
            json={
                "dashboard_title": title,
                "published": False,
                "json_metadata": json.dumps(
                    {"color_scheme": "metromove", "cross_filters_enabled": True}
                ),
            },
        )
        chart_ids, layout_rows = [], []
        for resolved, kind, name in resolved_plans:
            dataset_id = api.dataset_id(DATASET_BY_RELATION[resolved.relation])
            params = chart_form_data(resolved, dataset_id, kind)
            chart = api.call(
                "POST",
                "/api/v1/chart/",
                json={
                    "slice_name": f"{DRAFT_PREFIX}{name}",
                    "viz_type": params["viz_type"],
                    "datasource_id": dataset_id,
                    "datasource_type": "table",
                    "params": json.dumps(params),
                    "dashboards": [dashboard["id"]],
                    "description": f"Generated by the assistant from: {request.explanation}"[:400],
                },
            )
            chart_ids.append(chart["id"])
            layout_rows.append(chart["id"])
        position = {
            "DASHBOARD_VERSION_KEY": "v2",
            "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
            "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
            "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": title}},
        }
        for chart_id in layout_rows:
            row, item = f"ROW-{uuid.uuid4().hex[:8]}", f"CHART-{uuid.uuid4().hex[:8]}"
            position["GRID_ID"]["children"].append(row)
            position[row] = {
                "type": "ROW",
                "id": row,
                "children": [item],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            position[item] = {
                "type": "CHART",
                "id": item,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row],
                "meta": {"chartId": chart_id, "width": 12, "height": 50},
            }
        api.call(
            "PUT",
            f"/api/v1/dashboard/{dashboard['id']}",
            json={"position_json": json.dumps(position)},
        )

        report_id = uuid.uuid4().hex[:12]
        spec = {
            "request": request.model_dump(mode="json"),
            "charts": [
                {
                    "chart_id": cid,
                    "relation": r.relation,
                    "kind": k,
                    "months": r.months + r.comparison_months,
                }
                for cid, (r, k, _) in zip(chart_ids, resolved_plans, strict=True)
            ],
        }
        draft = Draft(
            report_id, request.dashboard_title, dashboard["id"], chart_ids, spec, previews
        )
        self.drafts[report_id] = draft
        return draft

    def confirm(self, report_id: str, confirm: bool, replace_existing: bool) -> Draft:
        draft = self.drafts.get(report_id)
        if draft is None:
            raise BuilderError(f"unknown draft {report_id}")
        if not confirm:
            raise BuilderError("publication needs explicit confirmation (confirm=true)")
        api = self.client()
        existing = api.dashboard_by_title(draft.title)
        if existing and existing["id"] != draft.dashboard_id and not replace_existing:
            raise BuilderError(
                f"a dashboard named '{draft.title}' already exists (id {existing['id']}); "
                "set replace_existing=true to replace it"
            )
        if existing and existing["id"] != draft.dashboard_id and replace_existing:
            api.call("DELETE", f"/api/v1/dashboard/{existing['id']}")
        api.call(
            "PUT",
            f"/api/v1/dashboard/{draft.dashboard_id}",
            json={"dashboard_title": draft.title, "published": True},
        )
        for chart_id in draft.chart_ids:
            current = api.call("GET", f"/api/v1/chart/{chart_id}")["result"]
            api.call(
                "PUT",
                f"/api/v1/chart/{chart_id}",
                json={"slice_name": current["slice_name"].removeprefix(DRAFT_PREFIX)},
            )
        draft.status = "published"
        return draft
