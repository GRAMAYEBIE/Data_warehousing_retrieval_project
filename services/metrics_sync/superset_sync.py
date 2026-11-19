"""metrics-sync, Superset part: certified datasets with the governed metrics.

Through the Superset REST API, idempotently (a re-run updates, never duplicates):
  1. the database connection, as `superset_reader` (SELECT on `analytics` only);
  2. one certified virtual dataset per published aggregate, joined to its dimensions and
     limited to complete months (months whose source file is loaded);
  3. on each dataset, every governed metric whose sql_expression only uses columns of
     that dataset, copied from the dbt semantic manifest, with label, description,
     unit and certification. Nothing is typed by hand;
  4. a role `Analyst Manhattan` with a row-level security rule (pickup borough).

Usage (environment: SUPERSET_URL, SUPERSET_ADMIN_PASSWORD, SUPERSET_READER_PASSWORD):
    python superset_sync.py --manifest dbt/target/semantic_manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

OWNER = "AYEBIE GRAM MESCHAC"
DATABASE_NAME = "NYC Taxi warehouse (published layer, read-only)"
METRIC_SOURCE = "Governed metric, defined in dbt/models/semantic/_metrics.yml"
# The four BI datasets read the materialized views built by the publication step
# (airflow/include/nyc_taxi_ops/publish.py, BI_VIEWS): dimensions already joined, complete
# months only, indexed. A chart is a scan of one indexed view; the first version, with the
# joins inside each dataset, timed out at 120 s on the development machine.
DATASETS = [
    {
        "name": "trips_daily",
        "description": (
            "Trips by pickup day, pickup zone, payment type, rate code, vendor and quality "
            "status (complete months only). Source: analytics.mv_trips_daily."
        ),
        "sql": "SELECT * FROM analytics.mv_trips_daily",
        "main_dttm_col": "date_day",
        "rls": True,
    },
    {
        "name": "trips_hourly",
        "description": (
            "Trips by pickup day and hour, pickup zone, service period, airport flag and "
            "quality status (complete months only). Source: analytics.mv_trips_hourly."
        ),
        "sql": "SELECT * FROM analytics.mv_trips_hourly",
        "main_dttm_col": "date_day",
        "rls": True,
    },
    {
        "name": "routes_monthly",
        "description": (
            "Valid trips by month and route (pickup zone to dropoff zone) and service period "
            "(complete months only). Source: analytics.mv_routes_monthly."
        ),
        "sql": "SELECT * FROM analytics.mv_routes_monthly",
        "main_dttm_col": "pickup_month",
        "rls": True,
    },
    {
        "name": "quality_daily",
        "description": (
            "Data quality by source month, pickup day, vendor, pickup zone and payment type: "
            "trips per status and per flag. Source: analytics.mv_quality_daily."
        ),
        "sql": "SELECT * FROM analytics.mv_quality_daily",
        "main_dttm_col": "date_day",
        "rls": True,
    },
    # Analyses computed at publication from the governed aggregates (valid trips only).
    # Their indicators are derived from governed metrics and labelled as such.
    {
        "name": "revenue_bridge",
        "description": (
            "Price-volume decomposition of the revenue change between consecutive complete "
            "months: previous revenue + volume effect + price effect = revenue. Derived from "
            "the governed metrics total_revenue and trips. Source: analytics.mv_revenue_bridge."
        ),
        "sql": "SELECT * FROM analytics.mv_revenue_bridge",
        "main_dttm_col": "month_start",
        "rls": False,
        "metrics": [
            (
                "revenue_bridge_amount",
                "sum(amount)",
                "Amount (USD)",
                "$,.3s",
                "Revenue of the previous month, then the volume and price effects.",
            ),
        ],
    },
    {
        "name": "dropoff_growth",
        "description": (
            "Drop-off zones: valid trips in the latest complete month versus the month before "
            "(zones with at least 500 trips). Derived from the governed metric trips. "
            "Source: analytics.mv_dropoff_growth."
        ),
        "sql": "SELECT * FROM analytics.mv_dropoff_growth",
        "main_dttm_col": None,
        "rls": False,
        "metrics": [
            (
                "zone_trip_change",
                "max(trip_change_pct) / 100.0",
                "Trip change (%)",
                ".1%",
                "Change in valid trips ending in the zone, latest month versus the month before.",
            ),
            (
                "trips_latest_month",
                "sum(trips_latest_month)",
                "Trips (latest month)",
                ",d",
                "Valid trips ending in the zone in the latest complete month.",
            ),
        ],
    },
    {
        "name": "route_duration_anomaly",
        "description": (
            "Routes slower than usual: average duration of the latest month versus the "
            "earlier months, by route and service period, scored with a robust z-score "
            "across all routes. Derived from the governed metric avg_duration. "
            "Source: analytics.mv_route_duration_anomaly."
        ),
        "sql": "SELECT * FROM analytics.mv_route_duration_anomaly",
        "main_dttm_col": None,
        "rls": True,
        "metrics": [
            (
                "route_anomaly_score",
                "max(robust_z)",
                "Robust z-score",
                ".2f",
                "(gap - median gap) / (1.4826 x MAD). Above 3: unusual slowdown.",
            ),
            (
                "route_duration_gap",
                "max(duration_gap_pct) / 100.0",
                "Duration gap (%)",
                ".1%",
                "Latest average duration versus the baseline of earlier months.",
            ),
        ],
    },
    {
        "name": "pipeline_health",
        "description": (
            "Operational signals of every pipeline run (freshness, volume change, rejected "
            "rows, late data, dbt test pass rate). Source: analytics.pipeline_signals."
        ),
        "sql": """
SELECT s.*, r.status AS run_status, r.published, r.started_at, r.finished_at
FROM analytics.pipeline_signals AS s
LEFT JOIN analytics.pipeline_runs AS r ON s.run_id = r.run_id""",
        "main_dttm_col": "measured_at",
        "rls": False,
    },
    {
        "name": "source_reconciliation",
        "description": (
            "Bronze to silver reconciliation per source month and ingestion batches. "
            "Source: analytics.recon_bronze_silver, analytics.ingestion_batches."
        ),
        "sql": """
SELECT r.*, b.status AS batch_status, b.schema_version, b.file_size_bytes, b.sha256,
    b.finished_at AS loaded_at
FROM analytics.recon_bronze_silver AS r
LEFT JOIN analytics.ingestion_batches AS b ON r.batch_id = b.batch_id""",
        "main_dttm_col": "loaded_at",
        "rls": False,
    },
    {
        "name": "pipeline_status",
        "description": (
            "Last publication: time, run, months covered, last ingestion. Used by the "
            "'last refreshed' tile of every dashboard. Source: analytics.pipeline_status."
        ),
        "sql": "SELECT * FROM analytics.pipeline_status",
        "main_dttm_col": "published_at",
        "rls": False,
    },
]

D3_FORMATS = {
    "USD": "$,.0f",
    "USD per trip": "$,.2f",
    "USD per card trip": "$,.2f",
    "USD per mile": "$,.2f",
    "ratio": ".1%",
    "trips": ",d",
    "trips per active hour": ",.1f",
    "miles": ",.0f",
    "miles per trip": ",.2f",
    "minutes": ",.0f",
    "minutes per trip": ",.1f",
    "hours": ",d",
    "kg CO2 (estimate)": ",.0f",
}


class Superset:
    """Small REST client. Retries on timeouts and dropped connections: on a busy host the
    single Superset web worker can take minutes to answer the first requests."""

    def __init__(self, url: str, password: str, attempts: int = 4) -> None:
        self.attempts = attempts
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=300)
        token = self.http.post(
            "/api/v1/security/login",
            json={"username": "admin", "password": password, "provider": "db", "refresh": False},
        )
        token.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        csrf = self.http.get("/api/v1/security/csrf_token/")
        csrf.raise_for_status()
        self.http.headers["X-CSRFToken"] = csrf.json()["result"]
        self.http.headers["Referer"] = url

    def call(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.http.request(method, path, **kwargs)
                break
            except (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError) as exc:
                if attempt == self.attempts:
                    raise
                wait = 15 * attempt
                print(f"    {method} {path}: {type(exc).__name__}, retry {attempt} in {wait} s")
                time.sleep(wait)
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:600]}")
        return response.json() if response.content else {}

    def find(self, resource: str, column: str, value: str) -> dict | None:
        query = {"filters": [{"col": column, "opr": "eq", "value": value}], "page_size": 1}
        result = self.call("GET", f"/api/v1/{resource}/", params={"q": json.dumps(query)})
        return result["result"][0] if result.get("result") else None


def ensure_database(api: Superset, reader_password: str) -> int:
    uri = f"postgresql+psycopg2://superset_reader:{reader_password}@postgres:5432/warehouse"
    body = {
        "database_name": DATABASE_NAME,
        "sqlalchemy_uri": uri,
        "expose_in_sqllab": True,
        "allow_dml": False,
        "allow_run_async": False,
        "extra": json.dumps({"schema_options": {"expand_rows": False}}),
    }
    existing = api.find("database", "database_name", DATABASE_NAME)
    if existing:
        api.call("PUT", f"/api/v1/database/{existing['id']}", json=body)
        return existing["id"]
    return api.call("POST", "/api/v1/database/", json=body)["id"]


SQL_WORDS = {"sum", "count", "distinct", "filter", "where", "nullif", "and", "or", "not", "null"}


def columns_in(expression: str) -> set[str]:
    """Column names an aggregate expression uses (string literals and SQL words removed)."""
    without_literals = re.sub(r"'[^']*'", "", expression.lower())
    return set(re.findall(r"[a-z_][a-z0-9_]*", without_literals)) - SQL_WORDS


def metric_payloads(catalog: list[dict], dataset_columns: set[str]) -> list[dict]:
    """Governed metrics computable on a dataset: every column they use exists there."""
    payloads = []
    for metric in catalog:
        meta = metric["config"]["meta"]
        expression = " ".join(str(meta["sql_expression"]).split())
        if not columns_in(expression) <= dataset_columns:
            continue
        estimate = " ESTIMATE." if meta.get("is_estimate") else ""
        payloads.append(
            {
                "metric_name": metric["name"],
                "verbose_name": metric.get("label") or metric["name"],
                "expression": expression,
                "description": " ".join((metric.get("description") or "").split()) + estimate,
                "d3format": D3_FORMATS.get(meta.get("unit", ""), ",.2f"),
                "warning_text": "Estimate, not a measurement." if meta.get("is_estimate") else None,
                "extra": json.dumps(
                    {
                        "certification": {
                            "certified_by": meta.get("owner", OWNER),
                            "details": METRIC_SOURCE,
                        }
                    }
                ),
            }
        )
    return payloads


def quality_rate_payloads(dataset_columns: set[str]) -> list[dict]:
    """Data-quality indicators of the quality dataset, generated from its columns.

    Every `<status or flag>_trip_count` column becomes a share of all trips. These are
    operational indicators (not business metrics); valid_share equals valid_trip_rate.
    """
    payloads = []
    for column in sorted(dataset_columns):
        match = re.fullmatch(r"([a-z_]+)_trip_count", column)
        if not match:
            continue
        code = match.group(1)
        name = f"{code}_share"
        payloads.append(
            {
                "metric_name": name,
                "verbose_name": f"Share of trips: {code.replace('_', ' ')}",
                "expression": f"sum({column}) / nullif(sum(trip_count), 0)",
                "description": (
                    f"Trips with {code.replace('_', ' ')} divided by all trips of the selection. "
                    "Data-quality indicator generated from the flag catalogue."
                ),
                "d3format": ".2%",
                "extra": json.dumps(
                    {"certification": {"certified_by": OWNER, "details": "Quality indicator"}}
                ),
            }
        )
    return payloads


def ensure_dataset(api: Superset, database_id: int, spec: dict, catalog: list[dict]) -> dict:
    existing = api.find("dataset", "table_name", spec["name"])
    if existing:
        dataset_id = existing["id"]
        api.call("PUT", f"/api/v1/dataset/{dataset_id}", json={"sql": spec["sql"].strip()})
    else:
        dataset_id = api.call(
            "POST",
            "/api/v1/dataset/",
            json={
                "database": database_id,
                "schema": "analytics",
                "table_name": spec["name"],
                "sql": spec["sql"].strip(),
            },
        )["id"]
    # Refresh column metadata from the database, then read it back.
    api.call("PUT", f"/api/v1/dataset/{dataset_id}/refresh")
    current = api.call("GET", f"/api/v1/dataset/{dataset_id}")["result"]
    column_names = {c["column_name"] for c in current["columns"]}
    metrics = metric_payloads(catalog, column_names)
    if spec["name"] == "quality_daily":
        metrics += quality_rate_payloads(column_names)
    for name, expression, label, d3format, description in spec.get("metrics", []):
        metrics.append(
            {
                "metric_name": name,
                "verbose_name": label,
                "expression": expression,
                "description": description + " Derived indicator (not a governed metric).",
                "d3format": d3format,
                "extra": json.dumps(
                    {
                        "certification": {
                            "certified_by": OWNER,
                            "details": "Derived from governed metrics at publication",
                        }
                    }
                ),
            }
        )
    # Keep ids of metrics that already exist so the update replaces them in place.
    known = {m["metric_name"]: m["id"] for m in current.get("metrics", [])}
    for metric in metrics:
        if metric["metric_name"] in known:
            metric["id"] = known[metric["metric_name"]]
    columns = [
        {
            k: c[k]
            for k in (
                "id",
                "column_name",
                "type",
                "is_dttm",
                "groupby",
                "filterable",
                "verbose_name",
                "description",
                "expression",
                "python_date_format",
            )
            if k in c
        }
        | {"is_dttm": c["column_name"] == spec["main_dttm_col"] or bool(c.get("is_dttm"))}
        for c in current["columns"]
    ]
    api.call(
        "PUT",
        f"/api/v1/dataset/{dataset_id}?override_columns=true",
        json={
            "description": spec["description"],
            "main_dttm_col": spec["main_dttm_col"],
            "columns": columns,
            "metrics": metrics,
            "extra": json.dumps(
                {
                    "certification": {
                        "certified_by": OWNER,
                        "details": "Published layer only (analytics), complete months, "
                        "metric expressions copied from the dbt semantic layer.",
                    }
                }
            ),
        },
    )
    return {"id": dataset_id, "name": spec["name"], "metrics": [m["metric_name"] for m in metrics]}


def ensure_rls(api: Superset, datasets: list[dict]) -> str:
    role = api.find("security/roles", "name", "Analyst Manhattan")
    role_id = (
        role["id"]
        if role
        else api.call("POST", "/api/v1/security/roles/", json={"name": "Analyst Manhattan"})["id"]
    )
    table_ids = [d["id"] for d, spec in zip(datasets, DATASETS, strict=True) if spec["rls"]]
    body = {
        "name": "Manhattan pickups only",
        "filter_type": "Regular",
        "tables": table_ids,
        "roles": [role_id],
        "clause": "pickup_borough = 'Manhattan'",
        "group_key": "borough",
        "description": "Analysts of the Manhattan team see Manhattan pickups only.",
    }
    existing = api.find("rowlevelsecurity", "name", body["name"])
    if existing:
        api.call("PUT", f"/api/v1/rowlevelsecurity/{existing['id']}", json=body)
    else:
        api.call("POST", "/api/v1/rowlevelsecurity/", json=body)
    return f"role {role_id}, {len(table_ids)} datasets"


def ensure_ai_builder(api: Superset, password: str) -> str:
    """Service account of the AI assistant: role Alpha (creates charts and dashboards; cannot
    manage users, roles or database connections). Its drafts are published only after a
    manager confirms in the assistant."""
    alpha = api.find("security/roles", "name", "Alpha")
    if not alpha:
        raise RuntimeError("Superset role Alpha not found (run superset init)")
    body = {
        "active": True,
        "email": "ai_builder@example.org",
        "first_name": "AI",
        "last_name": "Report builder",
        "username": "ai_builder",
        "roles": [alpha["id"]],
    }
    existing = api.find("security/users", "username", "ai_builder")
    if existing:
        api.call(
            "PUT", f"/api/v1/security/users/{existing['id']}", json=body | {"password": password}
        )
        return f"ai_builder updated (id {existing['id']}, role Alpha)"
    created = api.call("POST", "/api/v1/security/users/", json=body | {"password": password})
    return f"ai_builder created (id {created.get('id')}, role Alpha)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=Path("dbt/target/semantic_manifest.json"))
    args = parser.parse_args(argv)

    catalog = json.loads(args.manifest.read_text(encoding="utf-8"))["metrics"]
    api = Superset(
        os.environ.get("SUPERSET_URL", "http://superset:8088"),
        os.environ["SUPERSET_ADMIN_PASSWORD"],
    )
    database_id = ensure_database(api, os.environ["SUPERSET_READER_PASSWORD"])
    print(f"database: {DATABASE_NAME} (id {database_id})")
    datasets = []
    for spec in DATASETS:
        result = ensure_dataset(api, database_id, spec, catalog)
        datasets.append(result)
        print(
            f"dataset {result['name']} (id {result['id']}): {len(result['metrics'])} metrics "
            f"{', '.join(result['metrics'])}"
        )
    print("row-level security:", ensure_rls(api, datasets))
    if os.environ.get("SUPERSET_AI_PASSWORD"):
        print("service account:", ensure_ai_builder(api, os.environ["SUPERSET_AI_PASSWORD"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
