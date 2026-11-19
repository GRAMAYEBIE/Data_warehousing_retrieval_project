"""The governed vocabulary the assistant may use, and nothing else.

- Metrics: read from semantic.metric_catalog (copied from the dbt YAML by metrics-sync):
  name, definition and the SQL expression over the published aggregates.
- Relations: the only FROM clauses a query can have. Same joins as the certified
  Superset datasets, limited to complete months (months whose source file is loaded).
- Dimensions: an allow-list of columns, each available in given relations.
- Members: the real values of categorical dimensions, so a filter on "Manhatan" or on a
  zone that does not exist is rejected before any query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The views already hold complete months only; the condition is repeated as a safeguard.
COMPLETE_MONTHS = "a.month_start IN (SELECT source_month FROM analytics.recon_bronze_silver)"

# Each relation reads one BI materialized view (aggregate + dimensions already joined,
# indexed, rebuilt at each publication): measured 0.10 s instead of 0.83 s with five joins
# for the same breakdown, which matters under the assistant's 10 s statement limit.
RELATIONS: dict[str, dict] = {
    "daily": {
        "base_table": "analytics.agg_trips_daily",
        "from": "analytics.mv_trips_daily AS a",
        "where": COMPLETE_MONTHS,
        "date": "a.date_day",
        "columns": {
            "trip_count",
            "airport_trip_count",
            "sum_total_amount",
            "sum_fare_amount",
            "sum_extra_amount",
            "sum_mta_tax",
            "sum_tolls_amount",
            "sum_improvement_surcharge",
            "sum_congestion_surcharge",
            "sum_airport_fee",
            "sum_cbd_congestion_fee",
            "sum_tip_amount",
            "tip_recorded_trip_count",
            "sum_tip_amount_recorded",
            "sum_fare_amount_tip_recorded",
            "sum_trip_distance",
            "sum_duration_min",
            "sum_total_amount_with_distance",
            "sum_trip_distance_positive",
            "quality_status",
        },
    },
    "hourly": {
        "base_table": "analytics.agg_trips_hourly",
        "from": "analytics.mv_trips_hourly AS a",
        "where": COMPLETE_MONTHS,
        "date": "a.date_day",
        "columns": {
            "trip_count",
            "sum_total_amount",
            "sum_trip_distance",
            "sum_duration_min",
            "quality_status",
            "pickup_date_sk",
            "pickup_hour",
        },
    },
    "routes": {
        "base_table": "analytics.agg_routes_monthly",
        "from": "analytics.mv_routes_monthly AS a",
        "where": "a.pickup_month IN (SELECT source_month FROM analytics.recon_bronze_silver)",
        "date": "a.pickup_month",
        "columns": {
            "trip_count",
            "airport_trip_count",
            "sum_total_amount",
            "sum_fare_amount",
            "sum_trip_distance",
            "sum_duration_min",
            "sum_total_amount_with_distance",
            "sum_trip_distance_positive",
            "quality_status",
        },
    },
}


def _everywhere(column: str) -> dict[str, str]:
    return {"daily": column, "hourly": column, "routes": column}


@dataclass(frozen=True)
class Dimension:
    name: str
    sql: dict[str, str]  # relation -> column expression
    label: str
    categorical: bool = True


DIMENSIONS: dict[str, Dimension] = {
    d.name: d
    for d in [
        Dimension("pickup_borough", _everywhere("a.pickup_borough"), "Pickup borough"),
        Dimension("pickup_zone", _everywhere("a.pickup_zone"), "Pickup zone"),
        Dimension(
            "pickup_market_segment", _everywhere("a.pickup_market_segment"), "Market segment"
        ),
        Dimension("dropoff_borough", {"routes": "a.dropoff_borough"}, "Dropoff borough"),
        Dimension("dropoff_zone", {"routes": "a.dropoff_zone"}, "Dropoff zone"),
        Dimension("route", {"routes": "a.route"}, "Route"),
        Dimension("payment_type", {"daily": "a.payment_type_name"}, "Payment type"),
        Dimension("rate_code", {"daily": "a.rate_code_name"}, "Rate code"),
        Dimension("vendor", {"daily": "a.vendor_name"}, "Vendor"),
        Dimension("day_type", {"daily": "a.day_type", "hourly": "a.day_type"}, "Day type"),
        Dimension("day_of_week", {"daily": "a.day_name", "hourly": "a.day_name"}, "Day of week"),
        Dimension("pickup_hour", {"hourly": "a.pickup_hour"}, "Pickup hour", False),
        Dimension(
            "service_period",
            {"hourly": "a.service_period_name", "routes": "a.service_period_name"},
            "Service period",
        ),
        Dimension("is_airport_trip", {"hourly": "a.is_airport_trip"}, "Airport trip"),
    ]
}

GRAIN_SQL = {
    "day": "a.date_day",
    "week": "a.week_start",
    "month": "a.month_start",
}

# Topics the data cannot answer (exam: do not claim them without an external source).
UNSUPPORTED_TOPICS = {
    r"\bdriver(s)?\b.*\b(earn|income|pay|wage|salar)": "driver earnings are not in the data",
    r"\b(wait|waiting) time": "passenger wait time is not recorded",
    r"\bcancel": "cancellations are not recorded (only completed trips)",
    r"\b(rider|passenger)s?\b.*\b(identity|name|who|age|gender)": "rider identity is not recorded",
    r"\bprofit": "profitability needs costs, which are not in the data",
    r"\bweather|\brain\b|\bsnow": "weather is not part of the published data",
    r"\b(uber|lyft|green taxi|fhv|for-hire)": "only Yellow Taxi trips are loaded",
}

INJECTION_PATTERNS = [
    r"\b(drop|delete|truncate|alter|insert|update|grant|revoke|create)\s+(table|schema|role|"
    r"database|from|into|user)",
    r"ignore (all |your |the )?(previous |above )?(rules|instructions)",
    r";\s*--",
    r"\bpg_sleep\b|\bpg_read_file\b|\bcopy\b.*\bprogram\b",
]


@dataclass
class Catalog:
    metrics: dict[str, dict]
    members: dict[str, list[str]] = field(default_factory=dict)
    months: list[str] = field(default_factory=list)  # complete months, 'YYYY-MM'
    published_run: str = ""
    published_at: str = ""

    def metric_relations(self, name: str) -> list[str]:
        """Relations where every column of the metric's expression exists."""
        needed = columns_in(self.metrics[name]["sql_expression"])
        preferred = {"analytics.agg_trips_hourly": "hourly"}.get(
            self.metrics[name]["base_table"], "daily"
        )
        found = [r for r, spec in RELATIONS.items() if needed <= spec["columns"]]
        return sorted(found, key=lambda r: r != preferred)

    def summary(self) -> str:
        """Compact catalogue given to the LLM (names and definitions only)."""
        lines = ["METRICS (use these exact names):"]
        for name, m in self.metrics.items():
            lines.append(f"- {name}: {m['label']}. {m['description']} [{m['unit']}]")
        lines.append("DIMENSIONS (use these exact names):")
        for d in DIMENSIONS.values():
            example = ", ".join(self.members.get(d.name, [])[:6])
            lines.append(f"- {d.name}: {d.label}" + (f" (e.g. {example})" if example else ""))
        lines.append(f"DATA COVERAGE: complete months {', '.join(self.months)}.")
        return "\n".join(lines)


SQL_WORDS = {"sum", "count", "distinct", "filter", "where", "nullif", "and", "or", "not", "null"}


def columns_in(expression: str) -> set[str]:
    without_literals = re.sub(r"'[^']*'", "", expression.lower())
    return set(re.findall(r"[a-z_][a-z0-9_]*", without_literals)) - SQL_WORDS


def load_catalog(conn) -> Catalog:
    """Read the governed metrics, coverage and dimension members (as ai_reader)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, label, description, unit, base_table, sql_expression, filters,
                   is_estimate
            FROM semantic.metric_catalog WHERE role = 'governed' ORDER BY name
            """
        )
        metrics = {
            row[0]: {
                "label": row[1],
                "description": row[2],
                "unit": row[3],
                "base_table": row[4],
                "sql_expression": " ".join(row[5].split()),
                "filters": row[6],
                "is_estimate": row[7],
            }
            for row in cur.fetchall()
        }
        cur.execute(
            "SELECT to_char(source_month, 'YYYY-MM') FROM analytics.recon_bronze_silver "
            "ORDER BY source_month"
        )
        months = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT run_id, published_at::text FROM analytics.pipeline_status")
        run_id, published_at = cur.fetchone()
        members = {}
        member_sql = {
            "pickup_borough": "SELECT DISTINCT borough FROM analytics.dim_zone",
            "pickup_zone": "SELECT DISTINCT zone_name FROM analytics.dim_zone",
            "pickup_market_segment": "SELECT DISTINCT market_segment FROM analytics.dim_zone",
            "dropoff_borough": "SELECT DISTINCT borough FROM analytics.dim_zone",
            "dropoff_zone": "SELECT DISTINCT zone_name FROM analytics.dim_zone",
            "payment_type": "SELECT DISTINCT payment_type_name FROM analytics.dim_payment_type",
            "rate_code": "SELECT DISTINCT rate_code_name FROM analytics.dim_rate_code",
            "vendor": "SELECT DISTINCT vendor_name FROM analytics.dim_vendor",
            "day_type": "SELECT DISTINCT day_type FROM analytics.dim_date",
            "day_of_week": "SELECT DISTINCT day_name FROM analytics.dim_date",
            "service_period": (
                "SELECT DISTINCT service_period_name FROM analytics.dim_service_period"
            ),
        }
        for name, sql in member_sql.items():
            cur.execute(sql)
            members[name] = sorted(str(r[0]) for r in cur.fetchall() if r[0] is not None)
        members["is_airport_trip"] = ["true", "false"]
        members["pickup_hour"] = [str(h) for h in range(24)]
    return Catalog(metrics, members, months, run_id, published_at)
