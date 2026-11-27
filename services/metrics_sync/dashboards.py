"""Build the six strategic dashboards in Superset (exam Q7 and Q13), as code.

Every chart answers one strategic question of the exam (in its description), uses the
governed metrics of the certified datasets created by superset_sync.py, and is checked
server side: its query is run through the chart data API and the build fails when a
chart returns an error. The "So what?" insight of each dashboard is computed from the
published tables at build time (read-only role) and dated with the publication, so the
text never states a number the data does not support.

Usage (environment: SUPERSET_URL, SUPERSET_ADMIN_PASSWORD, SUPERSET_READER_PASSWORD):
    python dashboards.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field

import psycopg

from superset_sync import OWNER, Superset

# --------------------------------------------------------------------------- chart model


COLOR_SCHEME = "metromove"  # defined in infra/superset/superset_config.py
SEQUENTIAL_SCHEME = "metromove_seq"


@dataclass
class Chart:
    """One chart. kind:
    kpi        big number                      trend_kpi  big number with trend line
    line/area  time or category series         bar        vertical bars
    hbar       horizontal ranking              stacked    stacked bars
    mixed      bars (metrics) + line (metrics_b) on a second axis
    pie        donut                           table      aggregated table
    raw        raw rows                        heatmap    x by y matrix
    bubble     entity bubbles: x, y, size      treemap    nested rectangles (groupby levels)
    waterfall  ordered steps (x) of one metric, ending with the total
    """

    title: str
    dataset: str
    kind: str
    question: str
    metrics: list[str] = field(default_factory=list)
    x: str | None = None  # time column or category column
    grain: str | None = None  # P1D, P1W, P1M
    groupby: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)  # raw tables
    limit: int = 10000
    sort_by: str | None = None
    ascending: bool = False
    filters: list[dict] = field(default_factory=list)  # simple {"col","op","val"}
    width: int = 4
    height: int = 50
    y_format: str | None = None
    metrics_b: list[str] = field(default_factory=list)  # mixed: second axis
    y_format_b: str | None = None
    rolling: int | None = None  # rolling mean over N periods (trend under the noise)
    options: dict = field(default_factory=dict)  # extra form data
    having: str | None = None  # condition on aggregates, e.g. a minimum number of trips


@dataclass
class Dashboard:
    slug: str
    title: str
    question: str
    rows: list[list[Chart] | str]  # a str row is a section heading
    insight_sql: dict[str, str]
    insight_template: str
    filter_datasets: list[str]


# Weekly charts show complete weeks only: the week that runs past the end of the latest
# published month (and the cross-month trips of the next days) is cut. Observed: the weekly
# trips KPI read "-59 % vs previous period" for the three days of 28-30 September 2026.
# The flag is a column of the datasets (superset_sync.COMPLETE_WEEK).
WEEK_FILTER = {"col": "complete_week", "op": "==", "val": True}


def week_cut(chart: Chart) -> dict | None:
    """The filter keeping complete weeks, for a weekly chart; None otherwise."""
    return WEEK_FILTER if chart.grain == "P1W" and chart.x == "date_day" else None


def all_filters(chart: Chart) -> list[dict]:
    return chart.filters + ([WEEK_FILTER] if week_cut(chart) else [])


def adhoc(f: dict) -> dict:
    return {
        "clause": "WHERE",
        "expressionType": "SIMPLE",
        "subject": f["col"],
        "operator": f["op"],
        "comparator": f["val"],
    }


def form_data(chart: Chart, dataset_id: int) -> dict:
    return _form_data(chart, dataset_id) | chart.options


SERIES_STYLE = {
    "show_legend": True,
    "legendOrientation": "top",
    "legendType": "scroll",
    "rich_tooltip": True,
    "tooltipSortByMetric": True,
    "truncate_metric": True,
    "color_scheme": COLOR_SCHEME,
}


def _form_data(chart: Chart, dataset_id: int) -> dict:
    base = {
        "datasource": f"{dataset_id}__table",
        "viz_type": "",
        "adhoc_filters": [adhoc(f) for f in all_filters(chart)]
        + (
            [{"clause": "HAVING", "expressionType": "SQL", "sqlExpression": chart.having}]
            if chart.having
            else []
        ),
        "row_limit": chart.limit,
        "color_scheme": COLOR_SCHEME,
    }
    k = chart.kind
    if k in ("line", "area") and chart.grain:
        data = (
            base
            | SERIES_STYLE
            | {
                "viz_type": "echarts_area" if k == "area" else "echarts_timeseries_line",
                "x_axis": chart.x,
                "time_grain_sqla": chart.grain,
                "x_axis_sort_asc": True,
                "metrics": chart.metrics,
                "groupby": chart.groupby,
                "seriesType": "smooth",
                "markerEnabled": True,
                "markerSize": 5,
                "zoomable": True,
                "y_axis_format": chart.y_format or "SMART_NUMBER",
                "opacity": 0.35,
            }
        )
        if chart.rolling:
            data |= {"rolling_type": "mean", "rolling_periods": chart.rolling, "min_periods": 1}
        return data
    if k == "hbar":
        return (
            base
            | SERIES_STYLE
            | {
                "viz_type": "echarts_timeseries_bar",
                "orientation": "horizontal",
                "x_axis": chart.x,
                "metrics": chart.metrics,
                "groupby": chart.groupby,
                "x_axis_sort": chart.sort_by or chart.metrics[0],
                "x_axis_sort_asc": chart.ascending,
                "show_value": True,
                "y_axis_format": chart.y_format or "SMART_NUMBER",
                "show_legend": len(chart.metrics) > 1 or bool(chart.groupby),
            }
        )
    if k == "mixed":
        return (
            base
            | SERIES_STYLE
            | {
                "viz_type": "mixed_timeseries",
                "x_axis": chart.x,
                "time_grain_sqla": chart.grain,
                "metrics": chart.metrics,
                "metrics_b": chart.metrics_b,
                "groupby": [],
                "groupby_b": [],
                "adhoc_filters_b": [adhoc(f) for f in chart.filters],
                "seriesType": "bar",
                "seriesTypeB": "line",
                "yAxisIndex": 0,
                "yAxisIndexB": 1,
                "markerEnabledB": True,
                "y_axis_format": chart.y_format or "SMART_NUMBER",
                "y_axis_format_secondary": chart.y_format_b or "SMART_NUMBER",
                "zoomable": True,
            }
        )
    if k == "bubble":
        entity, series = chart.groupby[0], chart.groupby[1] if len(chart.groupby) > 1 else None
        return base | {
            "viz_type": "bubble_v2",
            "entity": entity,
            "series": series,
            "x": chart.metrics[0],
            "y": chart.metrics[1],
            "size": chart.metrics[2],
            "max_bubble_size": "40",
            "xAxisFormat": chart.options.get("xAxisFormat", "SMART_NUMBER"),
            "y_axis_format": chart.y_format or "SMART_NUMBER",
            "show_legend": True,
            "legendOrientation": "top",
            "opacity": 0.75,
            # Sort and limit by bubble size the way the bubble chart expects it (a raw
            # "orderby" list made the chart fail with "unhashable type: 'list'").
            "order_desc": True,
        }
    if k == "treemap":
        return base | {
            "viz_type": "treemap_v2",
            "groupby": chart.groupby,
            "metric": chart.metrics[0],
            "show_labels": True,
            "show_upper_labels": True,
            "label_type": "key_value",
            "number_format": chart.y_format or "SMART_NUMBER",
        }
    if k == "waterfall":
        # Steps are ordered labels ("1. ...", "2. ...", "3. ..."); Superset adds the total.
        return base | {
            "viz_type": "waterfall",
            "x_axis": chart.x,
            "metric": chart.metrics[0],
            "groupby": [],
            "show_value": True,
            "show_legend": False,
            "increase_color": {"r": 46, "g": 139, "b": 87, "a": 1},
            "decrease_color": {"r": 192, "g": 57, "b": 43, "a": 1},
            "total_color": {"r": 31, "g": 78, "b": 121, "a": 1},
            "x_ticks_layout": "auto",
            "y_axis_format": chart.y_format or "SMART_NUMBER",
        }
    if k == "kpi":
        return base | {
            "viz_type": "big_number_total",
            "metric": chart.metrics[0],
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": chart.y_format or "SMART_NUMBER",
        }
    if k == "trend_kpi":
        return base | {
            "viz_type": "big_number",
            "x_axis": chart.x,
            "time_grain_sqla": chart.grain or "P1W",
            "metric": chart.metrics[0],
            "compare_lag": 1,
            "compare_suffix": "vs previous period",
            "show_trend_line": True,
            "start_y_axis_at_zero": True,
            "y_axis_format": chart.y_format or "SMART_NUMBER",
        }
    if k in ("line", "bar", "stacked"):
        is_time = chart.grain is not None
        data = (
            base
            | SERIES_STYLE
            | {
                "viz_type": "echarts_timeseries_line" if k == "line" else "echarts_timeseries_bar",
                "x_axis": chart.x,
                "metrics": chart.metrics,
                "groupby": chart.groupby,
                "y_axis_format": chart.y_format or "SMART_NUMBER",
            }
        )
        if k == "line":
            data |= {"seriesType": "smooth", "markerEnabled": True, "markerSize": 5}
        if is_time:
            data["time_grain_sqla"] = chart.grain
            data["x_axis_sort_asc"] = True
            data["zoomable"] = True
        else:
            data["x_axis_sort"] = chart.sort_by or chart.metrics[0]
            data["x_axis_sort_asc"] = chart.ascending
            if k == "line":  # ordered categories such as hour of day
                data["x_axis_sort"] = chart.x
                data["x_axis_sort_asc"] = True
        if k == "stacked":
            data["stack"] = "Stack"
        if k == "bar" and not chart.groupby and len(chart.metrics) == 1:
            data["show_value"] = True
        return data
    if k == "pie":
        return base | {
            "viz_type": "pie",
            "groupby": chart.groupby,
            "metric": chart.metrics[0],
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
            "sort_by_metric": True,
        }
    if k == "table":
        return base | {
            "viz_type": "table",
            "query_mode": "aggregate",
            "groupby": chart.groupby,
            "metrics": chart.metrics,
            "timeseries_limit_metric": chart.sort_by or chart.metrics[0],
            "order_desc": not chart.ascending,
            "include_search": True,
        }
    if k == "raw":
        return base | {
            "viz_type": "table",
            "query_mode": "raw",
            "all_columns": chart.columns,
            "order_by_cols": [json.dumps([chart.sort_by, chart.ascending])]
            if chart.sort_by
            else [],
        }
    if k == "heatmap":
        return base | {
            "viz_type": "heatmap_v2",
            "x_axis": chart.x,
            "groupby": chart.groupby[0],
            "metric": chart.metrics[0],
            "linear_color_scheme": SEQUENTIAL_SCHEME,
            "normalize_across": "heatmap",
            "show_values": False,
            "y_axis_format": chart.y_format or "SMART_NUMBER",
        }
    raise ValueError(k)


def query_context(chart: Chart, dataset_id: int) -> dict:
    """Server-side query equivalent to the chart, used to verify it and to save it."""
    columns: list = []
    if (
        chart.kind
        in ("trend_kpi", "line", "area", "bar", "hbar", "stacked", "heatmap", "mixed", "waterfall")
        and chart.x
    ):
        if chart.grain:
            columns.append(
                {
                    "columnType": "BASE_AXIS",
                    "expressionType": "SQL",
                    "sqlExpression": chart.x,
                    "label": chart.x,
                    "timeGrain": chart.grain,
                }
            )
        else:
            columns.append(chart.x)
    columns += chart.groupby
    if chart.kind == "raw":
        columns = chart.columns
    # Raw rows: no metrics at all (None), otherwise Superset groups by the listed columns.
    metrics = None if chart.kind == "raw" else chart.metrics + chart.metrics_b
    query = {
        "columns": columns,
        "metrics": metrics,
        "filters": [{"col": f["col"], "op": f["op"], "val": f["val"]} for f in all_filters(chart)],
        "extras": {"having": chart.having} if chart.having else {},
        "row_limit": chart.limit,
        "orderby": (
            [[chart.sort_by or chart.metrics[-1 if chart.kind == "bubble" else 0], chart.ascending]]
            if chart.kind in ("table", "bar", "hbar", "bubble")
            and not chart.grain
            and chart.metrics
            else [[chart.x, True]]
            if chart.kind == "waterfall"
            else [[chart.sort_by, chart.ascending]]
            if chart.kind == "raw" and chart.sort_by
            else []
        ),
    }
    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "queries": [query],
        "form_data": form_data(chart, dataset_id),
        "result_format": "json",
        "result_type": "full",
    }


# ------------------------------------------------------------------------ dashboard specs

DATA_QUALITY = Chart(
    "Data quality: valid-trip rate",
    "trips_daily",
    "kpi",
    "Is the data behind this dashboard trustworthy enough to decide?",
    ["valid_trip_rate"],
    y_format=".1%",
    width=3,
    height=30,
)
LAST_REFRESH = Chart(
    "Last refreshed",
    "pipeline_status",
    "raw",
    "How fresh and how complete is the data?",
    columns=[
        "published_at",
        "latest_source_month",
        "first_pickup_date",
        "last_pickup_date",
        "run_id",
    ],
    width=9,
    height=30,
)

# Change of a measure of valid trips between the latest published month and the same
# month a year earlier, in percent; NULL (shown "n/a") when that month is not published.
YOY = """
    with last as (select max(source_month) as m from analytics.recon_bronze_silver),
    v as (select d.month_start, sum({measure}) filter (where quality_status = 'valid') as v
          from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk = d.date_sk
          where d.month_start in ((select m from last), (select m from last) - interval '1 year')
          group by 1)
    select round(100.0 * (max(v) filter (where month_start = (select m from last))
                 - max(v) filter (where month_start = (select m from last) - interval '1 year'))
           / nullif(max(v) filter (where month_start = (select m from last) - interval '1 year'), 0), 1)
    from v"""

DASHBOARDS = [
    Dashboard(
        slug="executive-pulse",
        title="1. Executive Pulse",
        question="Are Yellow Taxi trips and revenue healthy?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Trips (weekly trend)",
                    "trips_daily",
                    "trend_kpi",
                    "How are trips trending week by week?",
                    ["trips"],
                    "date_day",
                    "P1W",
                    width=3,
                    height=40,
                ),
                Chart(
                    "Total revenue (weekly trend)",
                    "trips_daily",
                    "trend_kpi",
                    "How is total revenue trending week by week?",
                    ["total_revenue"],
                    "date_day",
                    "P1W",
                    width=3,
                    height=40,
                    y_format="$,.3s",
                ),
                Chart(
                    "Average fare (weekly trend)",
                    "trips_daily",
                    "trend_kpi",
                    "How is the average fare trending?",
                    ["avg_fare"],
                    "date_day",
                    "P1W",
                    width=3,
                    height=40,
                    y_format="$,.2f",
                ),
                Chart(
                    "Valid-trip rate (weekly trend)",
                    "trips_daily",
                    "trend_kpi",
                    "Does the trend remain after removing invalid or suspicious records?",
                    ["valid_trip_rate"],
                    "date_day",
                    "P1W",
                    width=3,
                    height=40,
                    y_format=".1%",
                ),
            ],
            [
                Chart(
                    "Trips and revenue by month",
                    "trips_daily",
                    "bar",
                    "Which periods have the largest month-over-month change?",
                    ["trips", "total_revenue"],
                    "month_start",
                    "P1M",
                    width=6,
                ),
                Chart(
                    "What drives revenue: components by month (indicative)",
                    "trips_daily",
                    "stacked",
                    "Is revenue rising because of fares, tolls or congestion fees? "
                    "Components are reported differently by vendors: indicative only.",
                    [
                        "fare_amount_valid",
                        "tip_amount_card",
                        "congestion_surcharge_revenue",
                        "congestion_fee_revenue",
                        "airport_fee_revenue",
                    ],
                    "month_start",
                    "P1M",
                    width=6,
                    y_format="$,.3s",
                ),
            ],
            [
                Chart(
                    "Valid trips versus all trips (weekly)",
                    "trips_daily",
                    "line",
                    "Does the change remain after removing invalid or suspicious records?",
                    ["trips", "trips_all"],
                    "date_day",
                    "P1W",
                    width=6,
                ),
                Chart(
                    "Revenue by pickup borough and month",
                    "trips_daily",
                    "stacked",
                    "Which boroughs contribute most to growth or decline?",
                    ["total_revenue"],
                    "month_start",
                    "P1M",
                    ["pickup_borough"],
                    width=6,
                    y_format="$,.3s",
                ),
            ],
            "Year over year: the same month, one line per year",
            [
                Chart(
                    "Trips by calendar month, one line per year",
                    "trips_daily",
                    "line",
                    "Which periods have the largest year-over-year change in trips?",
                    ["trips"],
                    "month_of_year",
                    groupby=["year"],
                    width=6,
                ),
                Chart(
                    "Total revenue by calendar month, one line per year",
                    "trips_daily",
                    "line",
                    "Which periods have the largest year-over-year change in revenue?",
                    ["total_revenue"],
                    "month_of_year",
                    groupby=["year"],
                    width=6,
                    y_format="$,.3s",
                ),
            ],
            "Trend and reliability together",
            [
                Chart(
                    "Weekly trips (bars) and valid-trip rate (line)",
                    "trips_daily",
                    "mixed",
                    "Does the trend hold once invalid or suspicious records are removed?",
                    ["trips"],
                    "date_day",
                    "P1W",
                    metrics_b=["valid_trip_rate"],
                    y_format_b=".1%",
                    width=7,
                    height=55,
                ),
                Chart(
                    "Total revenue: weekly and 4-week rolling mean",
                    "trips_daily",
                    "area",
                    "What is the underlying revenue trend once weekly noise is removed?",
                    ["total_revenue"],
                    "date_day",
                    "P1W",
                    rolling=4,
                    y_format="$,.3s",
                    width=5,
                    height=55,
                ),
            ],
            "Why revenue changed in the latest month",
            [
                Chart(
                    "Revenue bridge: more trips or higher revenue per trip?",
                    "revenue_bridge",
                    "waterfall",
                    "Is revenue changing because there are more trips or because each trip "
                    "brings more? Previous month, then the volume effect and the price effect; "
                    "the last bar is the latest month.",
                    ["revenue_bridge_amount"],
                    "step",
                    filters=[{"col": "is_latest_month", "op": "==", "val": True}],
                    y_format="$,.4s",
                    width=12,
                    height=55,
                ),
            ],
        ],
        insight_sql={
            "months": "select count(*) from analytics.recon_bronze_silver",
            "first": "select to_char(min(source_month), 'Mon YYYY') from analytics.recon_bronze_silver",
            "last": "select to_char(max(source_month), 'Mon YYYY') from analytics.recon_bronze_silver",
            "trip_change": """
                with m as (select d.month_start, sum(trip_count) filter (where quality_status='valid') t
                  from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                  where d.month_start in (select source_month from analytics.recon_bronze_silver)
                  group by 1 order by 1 desc limit 2)
                select round(100.0*(max(t) filter (where month_start=(select max(month_start) from m))
                  - max(t) filter (where month_start=(select min(month_start) from m)))
                  / nullif(max(t) filter (where month_start=(select min(month_start) from m)),0),1) from m""",
            "rev_change": """
                with m as (select d.month_start, sum(sum_total_amount) filter (where quality_status='valid') r
                  from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                  where d.month_start in (select source_month from analytics.recon_bronze_silver)
                  group by 1 order by 1 desc limit 2)
                select round(100.0*(max(r) filter (where month_start=(select max(month_start) from m))
                  - max(r) filter (where month_start=(select min(month_start) from m)))
                  / nullif(max(r) filter (where month_start=(select min(month_start) from m)),0),1) from m""",
            "cbd_share": """
                select round(100.0*sum(sum_cbd_congestion_fee) filter (where quality_status='valid')
                  / nullif(sum(sum_total_amount) filter (where quality_status='valid'),0),1)
                from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where d.month_start = (select max(source_month) from analytics.recon_bronze_silver)""",
            "valid_rate": """
                select round(100.0*sum(trip_count) filter (where quality_status='valid')/sum(trip_count),1)
                from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where d.month_start in (select source_month from analytics.recon_bronze_silver)""",
            "previous": """
                select to_char(max(previous_month), 'Mon YYYY') from analytics.mv_revenue_bridge
                where is_latest_month""",
            # Same month a year earlier: n/a until thirteen months are published.
            "year_before": """
                select to_char(max(source_month) - interval '1 year', 'Mon YYYY')
                from analytics.recon_bronze_silver""",
            "yoy_trip_change": YOY.format(measure="trip_count"),
            "yoy_rev_change": YOY.format(measure="sum_total_amount"),
            "volume_effect": """
                select amount from analytics.mv_revenue_bridge where is_latest_month and step_order = 2""",
            "price_effect": """
                select amount from analytics.mv_revenue_bridge where is_latest_month and step_order = 3""",
        },
        insight_template=(
            "### So what?\n"
            "- In **{last}**, trips **{trip_change_text}** and revenue **{rev_change_text}** "
            "compared with {previous}.\n"
            "- Against the same month a year earlier ({year_before}), trips "
            "**{yoy_trip_change_text}** and revenue **{yoy_rev_change_text}**.\n"
            "- {volume_effect_text}, and {price_effect_text} (see the revenue bridge).\n"
            "- The CBD congestion fee, charged since 5 January 2025, makes up "
            "**{cbd_share} %** of revenue.\n"
            "- **{valid_rate} %** of trips pass the quality checks. Every figure here uses "
            "those trips only.\n\n"
            "**Next question:** why did revenue per trip change: shorter trips or different "
            "fares? See *4. Fare, Payment and Customer Signals*."
        ),
        filter_datasets=["trips_daily"],
    ),
    Dashboard(
        slug="demand-rhythm",
        title="2. Demand Rhythm",
        question="When should capacity and service attention increase?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Trips per active hour: hour of day by day of week",
                    "trips_hourly",
                    "heatmap",
                    "What are the busiest pickup hours by day of week?",
                    ["trips_per_active_hour"],
                    "pickup_hour",
                    None,
                    ["day_name"],
                    width=12,
                    height=60,
                ),
            ],
            [
                Chart(
                    "Trips by hour: weekday, weekend and public holiday",
                    "trips_hourly",
                    "line",
                    "How does weekday demand differ from weekend and holiday demand?",
                    ["trips_per_active_hour"],
                    "pickup_hour",
                    None,
                    ["day_type"],
                    width=6,
                ),
                Chart(
                    "Trips per active hour by borough and hour",
                    "trips_hourly",
                    "line",
                    "Which hours have the highest trips per active hour, by borough?",
                    ["trips_per_active_hour"],
                    "pickup_hour",
                    None,
                    ["pickup_borough"],
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown", "EWR"]}],
                    width=6,
                ),
            ],
            [
                Chart(
                    "Trips by service period",
                    "trips_hourly",
                    "bar",
                    "Where are the sharpest morning, evening and late-night peaks?",
                    ["trips", "trips_per_active_hour"],
                    "service_period_name",
                    width=4,
                ),
                Chart(
                    "Airport versus city trips by hour",
                    "trips_hourly",
                    "stacked",
                    "Are airport trips concentrated at different times from city trips?",
                    ["trips"],
                    "pickup_hour",
                    None,
                    ["is_airport_trip"],
                    width=4,
                ),
                Chart(
                    "Weekly trips (seasonality)",
                    "trips_hourly",
                    "line",
                    "Which periods show unusual seasonality or falling demand?",
                    ["trips"],
                    "date_day",
                    "P1W",
                    width=4,
                ),
            ],
            "Where demand concentrates",
            [
                Chart(
                    "Busiest pickup zones by trips per active hour",
                    "trips_hourly",
                    "hbar",
                    "Which zones need capacity first when they are active?",
                    ["trips_per_active_hour"],
                    "pickup_zone",
                    limit=15,
                    width=12,
                    height=60,
                ),
            ],
        ],
        insight_sql={
            "peak": """
                select d.day_name || ' ' || lpad(pickup_hour::text, 2, '0') || ':00'
                from analytics.agg_trips_hourly a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where quality_status='valid' and d.month_start in (select source_month from analytics.recon_bronze_silver)
                group by d.day_name, pickup_hour order by sum(trip_count)/count(distinct a.pickup_date_sk) desc limit 1""",
            "low": """
                select lpad(pickup_hour::text, 2, '0') || ':00'
                from analytics.agg_trips_hourly a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where quality_status='valid' and d.month_start in (select source_month from analytics.recon_bronze_silver)
                group by pickup_hour order by sum(trip_count) asc limit 1""",
            "airport_share": """
                select round(100.0*sum(trip_count) filter (where is_airport_trip)/sum(trip_count),1)
                from analytics.agg_trips_hourly a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where quality_status='valid' and d.month_start in (select source_month from analytics.recon_bronze_silver)""",
        },
        insight_template=(
            "### So what?\n"
            "- Demand peaks on **{peak}** and is lowest around **{low}**.\n"
            "- Airport trips are **{airport_share} %** of all trips and peak at different "
            "hours from city trips: plan airport and city capacity separately.\n"
            "- Trip counts show rides that happened, not riders who could not find a taxi.\n\n"
            "**Next question:** do the evening peaks hold on public holidays? Use the *Day "
            "type* lines above."
        ),
        filter_datasets=["trips_hourly"],
    ),
    Dashboard(
        slug="geography-routes",
        title="3. Geography and Route Opportunities",
        question="Where is the value moving?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Top pickup zones by trips",
                    "trips_daily",
                    "hbar",
                    "Which pickup zones generate the most trips?",
                    ["trips"],
                    "pickup_zone",
                    limit=15,
                    width=6,
                ),
                Chart(
                    "Pickup zones: trips, revenue and average fare",
                    "trips_daily",
                    "table",
                    "Which pickup zones generate the most revenue and revenue per trip?",
                    ["trips", "total_revenue", "avg_fare", "avg_distance"],
                    None,
                    None,
                    ["pickup_zone", "pickup_borough"],
                    limit=25,
                    width=6,
                ),
            ],
            [
                Chart(
                    "Demand mix by pickup borough",
                    "trips_daily",
                    "pie",
                    "How do the boroughs differ in demand mix?",
                    ["trips"],
                    None,
                    None,
                    ["pickup_borough"],
                    width=4,
                ),
                Chart(
                    "Most common routes",
                    "routes_monthly",
                    "table",
                    "What are the most common pickup-to-dropoff routes?",
                    ["trips", "total_revenue", "revenue_per_mile", "avg_duration"],
                    None,
                    None,
                    ["route"],
                    limit=20,
                    width=8,
                ),
            ],
            [
                Chart(
                    "High revenue per mile routes (at least 500 trips)",
                    "routes_monthly",
                    "table",
                    "Which routes have high revenue but low volume, or high volume but low "
                    "revenue per mile?",
                    ["revenue_per_mile", "trips", "avg_distance"],
                    None,
                    None,
                    ["route"],
                    limit=20,
                    sort_by="revenue_per_mile",
                    # A route with a handful of trips would top the list by chance.
                    having="sum(trip_count) >= 500",
                    width=6,
                ),
                Chart(
                    "Airport trips by pickup market segment",
                    "routes_monthly",
                    "bar",
                    "What share of trips start or end at airports, and where do they connect?",
                    ["airport_trips", "trips"],
                    "pickup_market_segment",
                    width=6,
                ),
            ],
            "Where the value is: distance, price and volume together",
            [
                Chart(
                    "Pickup zones: distance, revenue per mile and volume",
                    "trips_daily",
                    "bubble",
                    "Which zones combine long trips, high revenue per mile and high volume? "
                    "Bubble size is the number of trips.",
                    ["avg_distance", "revenue_per_mile", "trips"],
                    groupby=["pickup_zone", "pickup_borough"],
                    limit=60,
                    y_format="$,.2f",
                    options={
                        "xAxisFormat": ",.1f",
                        "x_axis_label": "Average distance (miles)",
                        "y_axis_label": "Revenue per mile (USD)",
                    },
                    width=7,
                    height=65,
                ),
                Chart(
                    "Revenue by borough and pickup zone",
                    "trips_daily",
                    "treemap",
                    "How concentrated is revenue across boroughs and zones?",
                    ["total_revenue"],
                    groupby=["pickup_borough", "pickup_zone"],
                    limit=80,
                    y_format="$,.3s",
                    width=5,
                    height=65,
                ),
            ],
            [
                Chart(
                    "Origin to destination: trips between boroughs",
                    "routes_monthly",
                    "heatmap",
                    "How do Manhattan, Brooklyn, Queens, Bronx and Staten Island exchange trips?",
                    ["trips"],
                    "dropoff_borough",
                    groupby=["pickup_borough"],
                    options={
                        "normalize_across": "heatmap",
                        "show_values": True,
                        "show_percentage": True,
                    },
                    width=12,
                    height=55,
                ),
            ],
            "Where trips are growing and declining (latest month versus the month before)",
            [
                Chart(
                    "Fastest-growing drop-off zones",
                    "dropoff_growth",
                    "hbar",
                    "Which drop-off zones are growing fastest? Zones with at least 500 trips "
                    "in the previous month.",
                    ["zone_trip_change"],
                    "dropoff_zone",
                    limit=10,
                    y_format=".1%",
                    width=6,
                    height=55,
                ),
                Chart(
                    "Fastest-declining drop-off zones",
                    "dropoff_growth",
                    "hbar",
                    "Which drop-off zones are declining fastest? Zones with at least 500 trips "
                    "in the previous month.",
                    ["zone_trip_change"],
                    "dropoff_zone",
                    limit=10,
                    ascending=True,
                    y_format=".1%",
                    width=6,
                    height=55,
                ),
            ],
        ],
        insight_sql={
            "growth_zone": """
                select dropoff_zone from analytics.mv_dropoff_growth
                order by trip_change_pct desc nulls last limit 1""",
            "growth_pct": """
                select round(trip_change_pct, 1) from analytics.mv_dropoff_growth
                order by trip_change_pct desc nulls last limit 1""",
            "top_zone": """
                select z.zone_name from analytics.agg_trips_daily a
                join analytics.dim_zone z on a.pickup_zone_sk=z.zone_sk
                where quality_status='valid' group by 1 order by sum(trip_count) desc limit 1""",
            "manhattan_share": """
                select round(100.0*sum(trip_count) filter (where z.borough='Manhattan')/sum(trip_count),1)
                from analytics.agg_trips_daily a join analytics.dim_zone z on a.pickup_zone_sk=z.zone_sk
                where quality_status='valid'""",
            "top_route": """
                select pz.zone_name || ' -> ' || dz.zone_name from analytics.agg_routes_monthly a
                join analytics.dim_zone pz on a.pickup_zone_sk=pz.zone_sk
                join analytics.dim_zone dz on a.dropoff_zone_sk=dz.zone_sk
                group by 1 order by sum(trip_count) desc limit 1""",
        },
        insight_template=(
            "### So what?\n"
            "- **{manhattan_share} %** of trips start in Manhattan. The busiest pickup zone is "
            "**{top_zone}** and the most common route is **{top_route}**.\n"
            "- The fastest-growing drop-off zone is **{growth_zone}**: **{growth_pct} %** more "
            "trips than the month before.\n"
            "- A few zones drive the totals, so a change there moves the whole network. Yellow "
            "taxis serve mostly Manhattan and the airports: this is not the whole city.\n\n"
            "**Next question:** are outer-borough routes growing too? Filter a borough in the "
            "left panel."
        ),
        filter_datasets=["trips_daily", "routes_monthly"],
    ),
    Dashboard(
        slug="fare-payment-signals",
        title="4. Fare, Payment and Customer Signals",
        question="What is changing in trip economics?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Average fare and average tip (card) by month",
                    "trips_daily",
                    "line",
                    "How are fares and tips changing over time?",
                    ["avg_fare", "avg_tip"],
                    "month_start",
                    "P1M",
                    width=6,
                    y_format="$,.2f",
                ),
                Chart(
                    "Tip rate (card trips) by pickup borough",
                    "trips_daily",
                    "bar",
                    "What is the tip rate by borough?",
                    ["tip_rate"],
                    "pickup_borough",
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown"]}],
                    width=6,
                    y_format=".1%",
                ),
            ],
            [
                Chart(
                    "Payment types by month",
                    "trips_daily",
                    "stacked",
                    "Are cash and card trip shares changing?",
                    ["trips"],
                    "month_start",
                    "P1M",
                    ["payment_type_name"],
                    width=6,
                ),
                Chart(
                    "Rate codes: fare, distance and duration",
                    "trips_daily",
                    "table",
                    "Which rate codes have the highest average fare, distance and duration?",
                    ["trips", "avg_fare", "avg_distance", "avg_duration"],
                    None,
                    None,
                    ["rate_code_name"],
                    width=6,
                ),
            ],
            [
                Chart(
                    "Revenue per mile by week",
                    "trips_daily",
                    "line",
                    "Is fare per mile changing independently of trip length?",
                    ["revenue_per_mile", "avg_distance"],
                    "date_day",
                    "P1W",
                    width=6,
                ),
                Chart(
                    "CBD congestion fee revenue by week",
                    "trips_daily",
                    "bar",
                    "How much revenue does the congestion fee represent, and when?",
                    ["congestion_fee_revenue"],
                    "date_day",
                    "P1W",
                    width=6,
                    y_format="$,.3s",
                ),
            ],
            "Price structure by borough",
            [
                Chart(
                    "Average fare by pickup borough",
                    "trips_daily",
                    "hbar",
                    "Which boroughs have the highest average fare?",
                    ["avg_fare"],
                    "pickup_borough",
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown"]}],
                    y_format="$,.2f",
                    width=6,
                ),
                Chart(
                    "Revenue per mile by pickup borough",
                    "trips_daily",
                    "hbar",
                    "Is the price per mile different between boroughs?",
                    ["revenue_per_mile"],
                    "pickup_borough",
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown"]}],
                    y_format="$,.2f",
                    width=6,
                ),
            ],
        ],
        insight_sql={
            "card_share": """
                select round(100.0*sum(trip_count) filter (where p.payment_type_name='Credit card')/sum(trip_count),1)
                from analytics.agg_trips_daily a join analytics.dim_payment_type p on a.payment_type_sk=p.payment_type_sk
                join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where quality_status='valid' and d.month_start = (select max(source_month) from analytics.recon_bronze_silver)""",
            "tip_rate": """
                select round(100.0*sum(sum_tip_amount_recorded) filter (where quality_status='valid')
                  /nullif(sum(sum_fare_amount_tip_recorded) filter (where quality_status='valid'),0),1)
                from analytics.agg_trips_daily""",
            "not_reported": """
                select round(100.0*sum(trip_count) filter (where p.payment_type_id=0)/sum(trip_count),1)
                from analytics.agg_trips_daily a join analytics.dim_payment_type p on a.payment_type_sk=p.payment_type_sk""",
        },
        insight_template=(
            "### So what?\n"
            "- **{card_share} %** of trips are paid by card, and card riders tip **{tip_rate} %** "
            "of the fare.\n"
            "- Tips are only recorded for card payments: fewer card trips would mean fewer "
            "*recorded* tips, not less generous riders.\n"
            "- **{not_reported} %** of trips have no payment type: a gap in vendor data, not a "
            "rider choice.\n\n"
            "**Next question:** is revenue per mile moving because of the congestion fee or "
            "because trips are shorter? Compare the two weekly charts."
        ),
        filter_datasets=["trips_daily"],
    ),
    Dashboard(
        slug="service-efficiency-anomalies",
        title="5. Service Efficiency and Anomalies",
        question="Where should leaders look closer?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Valid trips",
                    "quality_daily",
                    "kpi",
                    "What share of trips can support decisions?",
                    ["valid_share"],
                    y_format=".1%",
                    width=4,
                    height=30,
                ),
                Chart(
                    "Suspicious trips",
                    "quality_daily",
                    "kpi",
                    "What share of trips needs review?",
                    ["suspicious_share"],
                    y_format=".1%",
                    width=4,
                    height=30,
                ),
                Chart(
                    "Invalid trips",
                    "quality_daily",
                    "kpi",
                    "What share of trips is excluded?",
                    ["invalid_share"],
                    y_format=".1%",
                    width=4,
                    height=30,
                ),
            ],
            [
                Chart(
                    "Suspicious-trip share by vendor and week",
                    "quality_daily",
                    "line",
                    "Is the suspicious-trip rate changing by vendor or month?",
                    ["suspicious_share"],
                    "date_day",
                    "P1W",
                    ["vendor_name"],
                    width=6,
                    y_format=".1%",
                ),
                Chart(
                    "Quality flags (share of trips)",
                    "quality_daily",
                    "table",
                    "Which records imply implausible speeds, negative amounts, missing zones "
                    "or pickup after dropoff?",
                    [
                        "negative_amount_share",
                        "implausible_speed_share",
                        "unrealistic_duration_share",
                        "zero_distance_share",
                        "null_zone_share",
                        "pickup_after_dropoff_share",
                        "unknown_ratecode_share",
                        "not_reported_share",
                    ],
                    None,
                    None,
                    ["vendor_name"],
                    width=6,
                    y_format=".2%",
                ),
            ],
            [
                Chart(
                    "Average duration by hour (valid trips)",
                    "trips_hourly",
                    "line",
                    "Which hours have the longest average trip duration?",
                    ["avg_duration"],
                    "pickup_hour",
                    None,
                    width=4,
                ),
                Chart(
                    "Source months: rows and reconciliation",
                    "source_reconciliation",
                    "raw",
                    "Which ingestion batches or source months have unexpected row counts?",
                    columns=[
                        "source_month",
                        "file_rows",
                        "bronze_rows",
                        "silver_rows",
                        "unexplained_rows",
                        "valid_trip_rate_pct",
                        "batch_status",
                    ],
                    sort_by="source_month",
                    width=8,
                ),
            ],
            [
                Chart(
                    "Pipeline signals of each run",
                    "pipeline_health",
                    "raw",
                    "Which runs had warnings, and should decisions be paused?",
                    columns=[
                        "run_id",
                        "source_month",
                        "signal_name",
                        "signal_value",
                        "unit",
                        "status",
                        "threshold",
                    ],
                    sort_by="measured_at",
                    width=12,
                ),
            ],
            "Where the problems are",
            [
                Chart(
                    "Invalid-trip share by pickup borough",
                    "quality_daily",
                    "hbar",
                    "Is the rejected-trip rate different by borough?",
                    ["invalid_share"],
                    "pickup_borough",
                    y_format=".1%",
                    width=6,
                ),
                Chart(
                    "Suspicious-trip share by payment type",
                    "quality_daily",
                    "hbar",
                    "Is the suspicious-trip rate different by payment type?",
                    ["suspicious_share"],
                    "payment_type_name",
                    y_format=".1%",
                    width=6,
                ),
            ],
            "Routes slower than usual",
            [
                Chart(
                    "Routes with the biggest gap between usual and current duration",
                    "route_duration_anomaly",
                    "raw",
                    "Which routes show the biggest gap between normal and current duration? "
                    "Latest month versus earlier months, by service period (at least 100 trips "
                    "in both). Score above 3: an unusual slowdown compared with all routes.",
                    columns=[
                        "route",
                        "service_period_name",
                        "baseline_avg_minutes",
                        "current_avg_minutes",
                        "duration_gap_pct",
                        "robust_z",
                        "current_trips",
                    ],
                    sort_by="robust_z",
                    filters=[{"col": "robust_z", "op": "IS NOT NULL", "val": None}],
                    limit=25,
                    width=12,
                    height=60,
                ),
            ],
        ],
        insight_sql={
            "slow_route": """
                select route from analytics.mv_route_duration_anomaly
                order by robust_z desc nulls last limit 1""",
            "slow_period": """
                select service_period_name from analytics.mv_route_duration_anomaly
                order by robust_z desc nulls last limit 1""",
            "slow_gap": """
                select duration_gap_pct from analytics.mv_route_duration_anomaly
                order by robust_z desc nulls last limit 1""",
            "invalid": """
                select round(100.0*sum(invalid_trip_count)/sum(trip_count),1) from analytics.agg_quality_daily
                where source_month = (select max(source_month) from analytics.recon_bronze_silver)""",
            "negative": """
                select round(100.0*sum(negative_amount_trip_count)/sum(trip_count),1) from analytics.agg_quality_daily
                where source_month = (select max(source_month) from analytics.recon_bronze_silver)""",
            "worst_vendor": """
                select v.vendor_name from analytics.agg_quality_daily a join analytics.dim_vendor v on a.vendor_sk=v.vendor_sk
                group by 1 having sum(trip_count) > 10000
                order by sum(suspicious_trip_count)::numeric/sum(trip_count) desc limit 1""",
            "unexplained": "select coalesce(sum(unexplained_rows),0) from analytics.recon_bronze_silver",
        },
        insight_template=(
            "### So what?\n"
            "- **{invalid} %** of trips in the latest month are invalid; **{negative} %** have "
            "a negative amount (refunds and disputes, not real rides).\n"
            "- **{worst_vendor}** has the most suspicious trips: check its data before "
            "comparing vendors.\n"
            "- The most unusual slowdown is **{slow_route}** ({slow_period}): "
            "**{slow_gap} %** longer than usual.\n"
            "- Every loaded row is accounted for: **{unexplained}** unexplained rows.\n\n"
            "**Pause decisions** when the valid-trip rate falls below 85 % or a pipeline "
            "signal fails (the publication gate then keeps the previous data).\n\n"
            "**Next question:** is that slowdown real traffic or a data issue? Compare it with "
            "the implausible-speed share."
        ),
        filter_datasets=["quality_daily"],
    ),
    Dashboard(
        slug="city-airport-strategy",
        title="6. City and Airport Strategy",
        question="What action should we take next?",
        rows=[
            [DATA_QUALITY, LAST_REFRESH],
            [
                Chart(
                    "Airport trips by hour and day type",
                    "trips_hourly",
                    "line",
                    "How does airport demand change by weekday and hour?",
                    ["trips"],
                    "pickup_hour",
                    None,
                    ["day_type"],
                    filters=[{"col": "is_airport_trip", "op": "==", "val": True}],
                    width=6,
                ),
                Chart(
                    "Market mix by month: airport, Manhattan core, outer boroughs",
                    "trips_daily",
                    "stacked",
                    "What is the mix of airport, Manhattan core and outer-borough trips?",
                    ["trips"],
                    "month_start",
                    "P1M",
                    ["pickup_market_segment"],
                    width=6,
                ),
            ],
            [
                Chart(
                    "Demand versus revenue by month",
                    "trips_daily",
                    "line",
                    "Where do demand increases not come with similar revenue growth?",
                    ["trips", "total_revenue"],
                    "month_start",
                    "P1M",
                    width=6,
                ),
                Chart(
                    "Least-served zones (trip volume as a demand proxy)",
                    "trips_daily",
                    "table",
                    "Which zones appear underserved using trip volume as a demand proxy?",
                    ["trips", "avg_fare"],
                    None,
                    None,
                    ["pickup_zone", "pickup_borough"],
                    limit=20,
                    sort_by="trips",
                    ascending=True,
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown", "EWR"]}],
                    width=6,
                ),
            ],
            [
                Chart(
                    "Estimated CO2 by pickup borough (ESTIMATE)",
                    "trips_daily",
                    "bar",
                    "What is an estimated distance-based emissions indicator by borough? "
                    "0.400 kg CO2 per mile (US EPA typical passenger vehicle); estimate only.",
                    ["est_co2_kg"],
                    "pickup_borough",
                    filters=[{"col": "pickup_borough", "op": "NOT IN", "val": ["Unknown"]}],
                    width=12,
                ),
            ],
        ],
        insight_sql={
            "airport_share": """
                select round(100.0*sum(airport_trip_count) filter (where quality_status='valid')
                  /sum(trip_count) filter (where quality_status='valid'),1) from analytics.agg_trips_daily""",
            "outer_share": """
                select round(100.0*sum(trip_count) filter (where z.market_segment='Outer boroughs and upper Manhattan')
                  /sum(trip_count),1)
                from analytics.agg_trips_daily a join analytics.dim_zone z on a.pickup_zone_sk=z.zone_sk
                where quality_status='valid'""",
            "co2_t": """
                select to_char(round(sum(sum_trip_distance) filter (where quality_status='valid')*0.400/1000), 'FM999,999,999')
                from analytics.agg_trips_daily a join analytics.dim_date d on a.pickup_date_sk=d.date_sk
                where d.month_start = (select max(source_month) from analytics.recon_bronze_silver)""",
        },
        insight_template=(
            "### So what? Three actions for next month\n"
            "1. **Plan airport capacity on its own.** Airport trips are **{airport_share} %** of "
            "all trips and follow their own hours. *To confirm:* hourly airport demand next "
            "month, by airport.\n"
            "2. **Do not cut outer-borough service on this data alone.** They are only "
            "**{outer_share} %** of Yellow trips, and low volume does not prove low need. "
            "*To confirm:* add Green taxi and for-hire vehicle data, and wait times.\n"
            "3. **Track the congestion fee.** Compare trips and revenue per mile in the "
            "charging zone each month. *To confirm:* a before and after view including "
            "December 2024, before the fee.\n\n"
            "Estimated CO2 for the latest month: about **{co2_t} tonnes**. This is an estimate "
            "(distance x 0.400 kg per mile, US EPA typical car), not a measurement."
        ),
        filter_datasets=["trips_daily", "trips_hourly"],
    ),
]


# ------------------------------------------------------------------------------ building


def change_text(value: str) -> str:
    """'rose by 2.6 %', 'fell by 1.3 %' or 'stayed flat': easier to read than a signed number."""
    if value == "n/a":
        return "n/a"
    pct = float(value)
    if abs(pct) < 0.05:
        return "stayed flat"
    return f"{'rose' if pct > 0 else 'fell'} by {abs(pct):.1f} %"


def money_text(value: str) -> str:
    """'added $1.6M' or 'removed $1.3M' for a revenue effect in USD."""
    if value == "n/a":
        return "n/a"
    amount = float(value)
    size = f"${abs(amount) / 1e6:.1f}M" if abs(amount) >= 1e6 else f"${abs(amount) / 1e3:.0f}k"
    return f"{'added' if amount >= 0 else 'removed'} **{size}**"


# What a positive or negative effect means, so the sentence names the real cause.
EFFECT_SUBJECTS = {
    "volume_effect": ("More trips", "Fewer trips"),
    "price_effect": ("higher revenue per trip", "lower revenue per trip"),
}


def readable(values: dict[str, str]) -> dict[str, str]:
    """Adds a plain-English twin to each change (`*_change`) and effect (`*_effect`)."""
    for key, value in list(values.items()):
        if key.endswith("_change"):
            values[f"{key}_text"] = change_text(value)
        elif key.endswith("_effect"):
            up, down = EFFECT_SUBJECTS.get(key, ("The change", "The change"))
            subject = down if value != "n/a" and float(value) < 0 else up
            values[f"{key}_text"] = f"**{subject}** {money_text(value)}"
    return values


def facts(sql: dict[str, str]) -> dict[str, str]:
    """Numbers quoted in the insight blocks, read with the BI read-only role.

    superset_reader (SELECT on analytics only), not ai_reader: these texts belong to the
    dashboards, and the AI role's 10 s limit is meant for interactive questions.
    """
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "postgres"),
        dbname=os.environ.get("PGDATABASE", "warehouse"),
        user="superset_reader",
        password=os.environ["SUPERSET_READER_PASSWORD"],
        options="-c statement_timeout=120000 -c default_transaction_read_only=on",
    )
    values = {}
    with conn, conn.cursor() as cur:
        for key, query in sql.items():
            cur.execute(query)
            row = cur.fetchone()
            values[key] = "n/a" if not row or row[0] is None else str(row[0])
        cur.execute("select published_at, run_id from analytics.pipeline_status")
        published_at, run_id = cur.fetchone()
    values["stamp"] = f"Computed from publication `{run_id}` ({published_at:%Y-%m-%d %H:%M} UTC)."
    return readable(values)


def ensure_chart(
    api: Superset, chart: Chart, dataset_ids: dict[str, int], dashboard_id: int | None
) -> int:
    dataset_id = dataset_ids[chart.dataset]
    params = form_data(chart, dataset_id)
    context = query_context(chart, dataset_id)
    body = {
        "slice_name": chart.title,
        "viz_type": params["viz_type"],
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "params": json.dumps(params),
        "query_context": json.dumps(context),
        "description": f"Question: {chart.question}",
        "certified_by": OWNER,
        "certification_details": "Governed metrics from the dbt semantic layer",
    }
    if dashboard_id:
        body["dashboards"] = [dashboard_id]
    existing = api.find("chart", "slice_name", chart.title)
    if existing:
        # Shared charts (data quality, last refreshed) sit on every dashboard: keep the
        # dashboards they already belong to, otherwise each update would detach them.
        current = api.call("GET", f"/api/v1/chart/{existing['id']}")["result"]
        linked = {d["id"] for d in current.get("dashboards", [])}
        body["dashboards"] = sorted(linked | ({dashboard_id} if dashboard_id else set()))
        api.call("PUT", f"/api/v1/chart/{existing['id']}", json=body)
        chart_id = existing["id"]
    else:
        chart_id = api.call("POST", "/api/v1/chart/", json=body)["id"]
    # Server-side verification: the chart's query must run.
    result = api.call("POST", "/api/v1/chart/data", json=context)
    rows = result["result"][0].get("rowcount", 0)
    if result["result"][0].get("error"):
        raise RuntimeError(f"chart {chart.title!r}: {result['result'][0]['error']}")
    print(f"    chart {chart_id:>4} {rows:>6} rows  {chart.title}")
    return chart_id


def markdown(text: str) -> dict:
    return {"type": "MARKDOWN", "meta": {"code": text, "width": 12, "height": 50}}


def layout(rows: list[list[tuple[str, int | str, Chart | None]]], title: str) -> dict:
    """Superset position_json: header, grid, one ROW per row, charts and markdown inside."""
    pos: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": title}},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
    }
    for row in rows:
        row_id = f"ROW-{uuid.uuid4().hex[:10]}"
        pos["GRID_ID"]["children"].append(row_id)
        pos[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for kind, value, chart in row:
            item_id = f"{kind}-{uuid.uuid4().hex[:10]}"
            pos[row_id]["children"].append(item_id)
            if kind == "CHART":
                pos[item_id] = {
                    "type": "CHART",
                    "id": item_id,
                    "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "meta": {
                        "chartId": value,
                        "width": chart.width,
                        "height": chart.height,
                        "sliceName": chart.title,
                    },
                }
            else:
                pos[item_id] = {
                    "type": "MARKDOWN",
                    "id": item_id,
                    "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    # Section headings are short; insight blocks need room.
                    "meta": {
                        "code": value,
                        "width": 12,
                        "height": 8 if kind == "HEADING" else 50,
                    },
                }
    return pos


def native_filters(dataset_ids: dict[str, int], datasets: list[str]) -> list[dict]:
    filters = [
        {
            "id": "NATIVE_FILTER-pickup-date",
            "name": "Pickup date",
            "filterType": "filter_time",
            "targets": [{}],
            "controlValues": {},
            "defaultDataMask": {"filterState": {"value": "No filter"}, "extraFormData": {}},
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "type": "NATIVE_FILTER",
            "description": "Applies to every chart (pickup date).",
        }
    ]
    borough_dataset = next(
        (
            d
            for d in datasets
            if d in ("trips_daily", "trips_hourly", "quality_daily", "routes_monthly")
        ),
        None,
    )
    if borough_dataset:
        filters.append(
            {
                "id": "NATIVE_FILTER-pickup-borough",
                "name": "Pickup borough",
                "filterType": "filter_select",
                "targets": [
                    {
                        "datasetId": dataset_ids[borough_dataset],
                        "column": {"name": "pickup_borough"},
                    }
                ],
                "controlValues": {
                    "multiSelect": True,
                    "enableEmptyFilter": False,
                    "defaultToFirstItem": False,
                    "searchAllOptions": False,
                    "inverseSelection": False,
                },
                "defaultDataMask": {"filterState": {}, "extraFormData": {}},
                "cascadeParentIds": [],
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                "type": "NATIVE_FILTER",
                "description": "Filters every chart that has a pickup borough.",
            }
        )
    return filters


def build(api: Superset, spec: Dashboard, dataset_ids: dict[str, int]) -> int:
    print(f"  {spec.title}")
    existing = api.find("dashboard", "slug", spec.slug)
    meta = {
        "native_filter_configuration": native_filters(dataset_ids, spec.filter_datasets),
        "cross_filters_enabled": True,
        "color_scheme": COLOR_SCHEME,
        "label_colors": {
            "Manhattan": "#1F4E79",
            "Queens": "#F2A900",
            "Brooklyn": "#2E8B57",
            "Bronx": "#C0392B",
            "Staten Island": "#6C5B7B",
            "EWR": "#17A2B8",
            "Unknown": "#7F8C8D",
        },
        "refresh_frequency": 0,
    }
    base = {
        "dashboard_title": spec.title,
        "slug": spec.slug,
        "published": True,
        "json_metadata": json.dumps(meta),
        "certified_by": OWNER,
        "certification_details": "Approved published layer and governed metrics only",
    }
    dashboard_id = (
        existing["id"] if existing else api.call("POST", "/api/v1/dashboard/", json=base)["id"]
    )

    values = facts(spec.insight_sql)
    insight = spec.insight_template.format(**values) + f"\n\n_{values['stamp']}_"
    header = (
        f"## {spec.title}\n**Strategic question:** {spec.question}\n\n"
        "All figures use governed metrics on valid trips unless a chart says otherwise. "
        "Definitions: *Metric catalogue* (docs/metric_catalog.md). Data owner: "
        f"{OWNER}."
    )
    rows: list = [[("MARKDOWN", header, None)]]
    for row in spec.rows:
        if isinstance(row, str):  # section heading
            rows.append([("HEADING", f"### {row}", None)])
            continue
        built = []
        for item in row:
            chart_id = ensure_chart(api, item, dataset_ids, dashboard_id)
            built.append(("CHART", chart_id, item))
        rows.append(built)
    rows.append([("MARKDOWN", insight, None)])
    api.call(
        "PUT",
        f"/api/v1/dashboard/{dashboard_id}",
        json=base | {"position_json": json.dumps(layout(rows, spec.title))},
    )
    return dashboard_id


def main() -> int:
    api = Superset(
        os.environ.get("SUPERSET_URL", "http://superset:8088"),
        os.environ["SUPERSET_ADMIN_PASSWORD"],
    )
    names = {
        "trips_daily",
        "trips_hourly",
        "routes_monthly",
        "quality_daily",
        "revenue_bridge",
        "dropoff_growth",
        "route_duration_anomaly",
        "pipeline_health",
        "source_reconciliation",
        "pipeline_status",
    }
    dataset_ids = {}
    for name in names:
        found = api.find("dataset", "table_name", name)
        if not found:
            raise SystemExit(f"dataset {name} missing: run superset_sync.py first")
        dataset_ids[name] = found["id"]
    built = [build(api, spec, dataset_ids) for spec in DASHBOARDS]
    print(f"{len(built)} dashboards built: {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
