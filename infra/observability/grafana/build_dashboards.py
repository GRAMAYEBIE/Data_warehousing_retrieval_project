"""Grafana dashboards as code: one file per dashboard in dashboards/.

    python infra/observability/grafana/build_dashboards.py

Six dashboards follow the data through the platform. The first answers "where is the
problem?" with one status per layer; each tile links to the dashboard that explains it.
Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
TEMPO = {"type": "tempo", "uid": "tempo"}
PG = {"type": "grafana-postgresql-datasource", "uid": "warehouse"}
GREEN, YELLOW, RED, BLUE = "green", "#EAB839", "red", "#1F4E79"


class Board:
    """Panels are laid out left to right on a 24-column grid, wrapping to new rows."""

    def __init__(self, uid: str, title: str, description: str, tags: list[str]):
        self.uid, self.title, self.description, self.tags = uid, title, description, tags
        self.panels: list[dict] = []
        self.x = self.y = self.row_height = 0
        self.links: list[dict] = []

    def _place(self, width: int, height: int) -> dict:
        if self.x + width > 24:
            self.x, self.y = 0, self.y + self.row_height
            self.row_height = 0
        pos = {"x": self.x, "y": self.y, "w": width, "h": height}
        self.x += width
        self.row_height = max(self.row_height, height)
        return pos

    def section(self, title: str) -> None:
        if self.x:
            self.x, self.y = 0, self.y + self.row_height
        self.panels.append(
            {"type": "row", "title": title, "collapsed": False, "id": len(self.panels) + 1,
             "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []}
        )  # fmt: skip
        self.y += 1
        self.row_height = 0

    def add(self, panel: dict, width: int, height: int) -> None:
        panel["id"] = len(self.panels) + 1
        panel["gridPos"] = self._place(width, height)
        self.panels.append(panel)

    def link(self, title: str, uid: str) -> None:
        self.links.append(
            {"title": title, "type": "link", "url": f"/d/{uid}", "targetBlank": False,
             "icon": "dashboard"}
        )  # fmt: skip

    def json(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.title,
            "description": self.description,
            "tags": ["nyc-taxi", *self.tags],
            "timezone": "browser",
            "schemaVersion": 41,
            "version": 1,
            "editable": False,
            "graphTooltip": 1,
            "refresh": "1m",
            "time": {"from": "now-24h", "to": "now"},
            "links": self.links,
            "panels": self.panels,
            "templating": {"list": []},
        }


def thresholds(*steps: tuple[float | None, str]) -> dict:
    return {"mode": "absolute", "steps": [{"value": v, "color": c} for v, c in steps]}


def prom(expr: str, legend: str = "", instant: bool = False, ref: str = "A",
         as_table: bool = False) -> dict:  # fmt: skip
    """as_table: one row per series with its labels as columns (not one column per series)."""
    target = {"datasource": PROM, "expr": expr, "legendFormat": legend, "refId": ref,
              "instant": instant, "range": not instant}  # fmt: skip
    if as_table:
        target["format"] = "table"
    return target


def count(expr: str) -> str:
    """Counters are extrapolated by increase(): round them, a number of answers is whole."""
    return f"round({expr})"


def sql(query: str, ref: str = "A") -> dict:
    return {"datasource": PG, "rawSql": query.strip(), "format": "table", "refId": ref,
            "editorMode": "code", "rawQuery": True}  # fmt: skip


def stat(title: str, target: dict, unit: str = "none", steps=None, description: str = "",
         link: tuple[str, str] | None = None, mappings=None,
         no_value: str = "no data") -> dict:  # fmt: skip
    panel = {
        "type": "stat",
        "title": title,
        "description": description,
        "datasource": target["datasource"],
        "targets": [target],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": steps or thresholds((None, GREEN)),
                "color": {"mode": "thresholds"},
                "mappings": mappings or [],
                "noValue": no_value,
            },
            "overrides": [],
        },
        "options": {"colorMode": "background", "graphMode": "none", "textMode": "value",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    }  # fmt: skip
    if link:
        panel["fieldConfig"]["defaults"]["links"] = [{"title": link[0], "url": f"/d/{link[1]}"}]
    return panel


def series(title: str, targets: list[dict], unit: str = "short", description: str = "",
           stack: bool = False, kind: str = "line") -> dict:  # fmt: skip
    return {
        "type": "timeseries",
        "title": title,
        "description": description,
        "datasource": targets[0]["datasource"],
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"drawStyle": kind, "fillOpacity": 25 if stack else 8,
                           "lineWidth": 2, "showPoints": "never",
                           "stacking": {"mode": "normal" if stack else "none"}},
            },
            "overrides": [],
        },  # fmt: skip
        "options": {"legend": {"displayMode": "table", "placement": "bottom",
                               "calcs": ["lastNotNull", "max"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }  # fmt: skip


def table(title: str, target: dict, description: str = "", overrides=None) -> dict:
    panel = {
        "type": "table",
        "title": title,
        "description": description,
        "datasource": target["datasource"],
        "targets": [target],
        "fieldConfig": {"defaults": {"custom": {"cellOptions": {"type": "auto"}}},
                        "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm"},
    }  # fmt: skip
    if target.get("format") == "table" and target["datasource"] == PROM:
        # Prometheus table: hide the time and the technical labels, keep what reads.
        panel["transformations"] = [{"id": "organize", "options": {
            "excludeByName": {"Time": True, "__name__": True, "instance": True}}}]  # fmt: skip
    return panel


def colored(column: str, steps: dict) -> dict:
    """Override: color the cell background of one column by thresholds."""
    return {"matcher": {"id": "byName", "options": column},
            "properties": [{"id": "thresholds", "value": steps},
                           {"id": "custom.cellOptions",
                            "value": {"type": "color-background", "mode": "basic"}}]}  # fmt: skip


def text(title: str, markdown: str) -> dict:
    return {"type": "text", "title": title, "options": {"mode": "markdown", "content": markdown}}


def logs(title: str, query: str) -> dict:
    return {"type": "logs", "title": title, "datasource": LOKI,
            "targets": [{"datasource": LOKI, "expr": query, "refId": "A"}],
            "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending",
                        "enableLogDetails": True}}  # fmt: skip


UP = {"type": "value", "options": {"0": {"text": "DOWN", "color": RED},
                                   "1": {"text": "UP", "color": GREEN}}}  # fmt: skip
BOOL_FAILED = [{"type": "value", "options": {"0": {"text": "OK", "color": GREEN},
                                              "1": {"text": "FAILED", "color": RED}}}]  # fmt: skip
UIDS = {
    "overview": "nyc-overview",
    "pipeline": "nyc-pipeline",
    "quality": "nyc-quality",
    "infra": "nyc-infrastructure",
    "bi": "nyc-bi",
    "ai": "nyc-ai-assistant",
}


def with_links(board: Board) -> Board:
    for name, title in [("overview", "Overview"), ("pipeline", "Pipeline"),
                        ("quality", "Data quality"), ("infra", "Infrastructure"),
                        ("bi", "BI"), ("ai", "AI assistant")]:  # fmt: skip
        if UIDS[name] != board.uid:
            board.link(title, UIDS[name])
    return board


# ------------------------------------------------------------------------------ boards
def overview() -> Board:
    b = with_links(Board(UIDS["overview"], "0. Platform overview: where is the problem?",
                         "One status per layer, in the order the data flows. Red names the "
                         "layer; click the tile for the dashboard that explains it.",
                         ["overview"]))  # fmt: skip
    b.add(text("How to read this page",
               "Data flows **left to right**: source file -> landing and bronze -> dbt "
               "silver/gold -> publication gate -> Superset and the AI assistant, on one "
               "host. A red tile names the layer at fault; its link opens the explanation. "
               "Logs and traces of a failing step are one click away (Explore -> Loki or "
               "Tempo)."), 24, 3)  # fmt: skip
    b.section("1. Source and ingestion")
    b.add(stat("Batches not loaded",
               prom('count(nyc_ingestion_rows_bronze{status!~"loaded|skipped_unchanged"}) '
                    "or vector(0)", instant=True),
               steps=thresholds((None, GREEN), (1, RED)),
               description="Ingestion batches whose latest attempt did not end loaded.",
               link=("Pipeline", UIDS["pipeline"])), 6, 4)  # fmt: skip
    b.add(stat("Months published", prom("nyc_pipeline_months_published", instant=True),
               steps=thresholds((None, RED), (6, GREEN)),
               description="Complete source months in the publication (exam: at least 6).",
               link=("Data quality", UIDS["quality"])), 6, 4)  # fmt: skip
    b.add(stat("Days since last publication", prom("nyc_pipeline_data_age_days", instant=True),
               unit="d", steps=thresholds((None, GREEN), (35, YELLOW), (45, RED)),
               description="Monthly cadence: 45 days means a missed month.",
               link=("Pipeline", UIDS["pipeline"])), 6, 4)  # fmt: skip
    b.add(stat("Last pipeline run", prom("nyc_pipeline_last_run_failed", instant=True),
               mappings=BOOL_FAILED, description="Outcome of the last monthly run.",
               link=("Pipeline", UIDS["pipeline"])), 6, 4)  # fmt: skip
    b.section("2. Transformation and quality")
    b.add(stat("dbt tests failed (last run)",
               prom("nyc_pipeline_dbt_failed_tests_last_run", instant=True),
               steps=thresholds((None, GREEN), (1, RED)),
               link=("Pipeline", UIDS["pipeline"])), 6, 4)  # fmt: skip
    b.add(stat("Valid-trip rate, latest month",
               prom("nyc_quality_valid_trip_rate_latest", instant=True), unit="percentunit",
               steps=thresholds((None, RED), (0.85, YELLOW), (0.9, GREEN)),
               description="Below 85 %: decisions on that month are paused.",
               link=("Data quality", UIDS["quality"])), 6, 4)  # fmt: skip
    b.add(stat("Unexplained rows bronze -> silver",
               prom("nyc_quality_unexplained_rows", instant=True),
               steps=thresholds((None, GREEN), (1, RED)),
               link=("Data quality", UIDS["quality"])), 6, 4)  # fmt: skip
    b.add(stat("Failing operational signals", prom("sum(nyc_signal_failed) or vector(0)",
                                                   instant=True),
               steps=thresholds((None, GREEN), (1, RED)),
               link=("Pipeline", UIDS["pipeline"])), 6, 4)  # fmt: skip
    b.section("3. Consumers: BI and AI")
    b.add(stat("AI assistant", prom('max(up{job="assistant"}) or vector(0)', instant=True),
               mappings=[UP], link=("AI assistant", UIDS["ai"])), 6, 4)  # fmt: skip
    b.add(stat("AI median answer time (1 h)",
               prom("histogram_quantile(0.5, sum by (le) (rate(assistant_answer_seconds_bucket[1h])))",
                    instant=True), unit="s",
               steps=thresholds((None, GREEN), (180, YELLOW), (300, RED)),
               link=("AI assistant", UIDS["ai"]), no_value="no question (1 h)"), 6, 4)  # fmt: skip
    b.add(stat("Narratives replaced (24 h)",
               prom(count('sum(increase(assistant_narrative_checks_total{check="replaced"}[24h])) '
                          "or vector(0)"), instant=True),
               steps=thresholds((None, GREEN), (3, YELLOW)),
               description="Answers whose model text cited a number or ranking not in the "
                           "result: caught and replaced.",
               link=("AI assistant", UIDS["ai"])), 6, 4)  # fmt: skip
    b.add(stat("BI cache (Redis)", prom("max(redis_up) or vector(0)", instant=True),
               mappings=[UP], description="Redis itself (not its exporter). Down when the bi "
                                          "profile is stopped.",
               link=("BI", UIDS["bi"])), 6, 4)  # fmt: skip
    b.section("4. Host")
    b.add(stat("Memory used", prom("1 - node_memory_MemAvailable_bytes / "
                                   "node_memory_MemTotal_bytes", instant=True),
               unit="percentunit", steps=thresholds((None, GREEN), (0.8, YELLOW), (0.92, RED)),
               link=("Infrastructure", UIDS["infra"])), 6, 4)  # fmt: skip
    b.add(stat("Swap used", prom("1 - node_memory_SwapFree_bytes / node_memory_SwapTotal_bytes",
                                 instant=True),
               unit="percentunit", steps=thresholds((None, GREEN), (0.25, YELLOW), (0.5, RED)),
               link=("Infrastructure", UIDS["infra"])), 6, 4)  # fmt: skip
    b.add(stat("Container restarts (1 h)",
               prom(count('sum(changes(container_start_time_seconds{name=~"nyc-taxi-insight-hub-.*"}[1h]))'
                          " or vector(0)"), instant=True),
               steps=thresholds((None, GREEN), (1, YELLOW)),
               link=("Infrastructure", UIDS["infra"])), 6, 4)  # fmt: skip
    b.add(stat("Alerts firing", prom('count(ALERTS{alertstate="firing"}) or vector(0)',
                                     instant=True),
               steps=thresholds((None, GREEN), (1, RED))), 6, 4)  # fmt: skip
    b.section("Details")
    b.add(table("Alerts firing now",
                prom('ALERTS{alertstate="firing"}', instant=True, as_table=True),
                description="Empty when nothing is wrong."), 12, 8)  # fmt: skip
    b.add(table("Every component: up or down",
                prom("up", instant=True, as_table=True),
                overrides=[colored("Value", thresholds((None, RED), (1, GREEN)))]), 12, 8)
    return b


def pipeline() -> Board:
    b = with_links(Board(UIDS["pipeline"], "1. Pipeline: runs, tasks, tests",
                         "Monthly runs from the operational tables, task durations from "
                         "Airflow, dbt tests of the last run.", ["pipeline"]))  # fmt: skip
    b.add(table("Pipeline runs (latest first)", sql("""
        SELECT run_id, source_month, status, published, forced,
               round(extract(epoch FROM finished_at - started_at) / 60) AS minutes,
               started_at, message
        FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 25"""),
                description="One row per Airflow run (run id as in Airflow)."), 24, 9)
    b.add(table("Operational signals, latest value", sql("""
        SELECT DISTINCT ON (signal_name) signal_name, signal_value, unit, threshold, status,
               run_id, measured_at
        FROM ops.pipeline_signals ORDER BY signal_name, measured_at DESC""")), 12, 8)
    b.add(table("dbt tests not passing (last run)", sql("""
        WITH last_run AS (SELECT run_id FROM ops.dbt_test_results ORDER BY recorded_at DESC LIMIT 1)
        SELECT unique_id, status, failures, round(execution_time::numeric, 1) AS seconds, message
        FROM ops.dbt_test_results
        WHERE run_id IN (SELECT run_id FROM last_run) AND status <> 'pass'
        ORDER BY status, unique_id"""),
                description="Empty when every test passed."), 12, 8)  # fmt: skip
    b.add(table("Ingestion batches", sql("""
        SELECT dataset, to_char(source_month, 'YYYY-MM') AS month, status, row_count_file,
               row_count_bronze, round(file_size_bytes / 1048576.0, 1) AS mb,
               schema_version, left(sha256, 12) AS sha256, started_at, error_message
        FROM ops.ingestion_manifest ORDER BY started_at DESC LIMIT 20""")), 24, 8)
    b.section("Airflow (StatsD)")
    b.add(series("Task duration", [prom(
        "max by (task_id) (rate(airflow_task_duration_seconds_sum[15m]) / "
        "rate(airflow_task_duration_seconds_count[15m]))", "{{task_id}}")], unit="s"), 12, 8)
    b.add(series("Tasks finished by state", [prom(
        "sum by (state) (increase(airflow_task_finished_total[1h]))", "{{state}}")],
        stack=True, kind="bars"), 12, 8)  # fmt: skip
    b.add(series("Scheduler heartbeat", [prom("rate(airflow_scheduler_heartbeat_total[5m])",
                                              "heartbeats/s")],
                 description="Flat at zero: the scheduler is not running or stalled."), 12, 6)
    b.add(logs("Airflow errors", '{service=~"airflow.*"} |~ "(?i)error|failed|exception"'), 12, 6)
    return b


def quality() -> Board:
    b = with_links(Board(UIDS["quality"], "2. Data quality",
                         "Bronze to silver reconciliation and quality flags per source month "
                         "(the publication gate uses the same numbers).", ["quality"]))
    b.add(stat("Valid-trip rate, latest month",
               prom("nyc_quality_valid_trip_rate_latest", instant=True), unit="percentunit",
               steps=thresholds((None, RED), (0.85, YELLOW), (0.9, GREEN))), 8, 4)  # fmt: skip
    b.add(stat("Invalid trips, all months", prom("nyc_quality_invalid_rate", instant=True),
               unit="percentunit", steps=thresholds((None, GREEN), (0.08, YELLOW), (0.15, RED))),
          8, 4)  # fmt: skip
    b.add(stat("Unexplained rows", prom("nyc_quality_unexplained_rows", instant=True),
               steps=thresholds((None, GREEN), (1, RED))), 8, 4)  # fmt: skip
    b.add(table("Reconciliation per source month", sql("""
        SELECT to_char(source_month, 'YYYY-MM') AS month, file_rows, bronze_rows, silver_rows,
               quarantine_rows, unexplained_rows, valid_rows, suspicious_rows, invalid_rows,
               valid_trip_rate_pct, unexplained_amount
        FROM analytics.recon_bronze_silver ORDER BY source_month"""),
                overrides=[colored("valid_trip_rate_pct", thresholds((None, RED), (85, YELLOW),
                                                                     (90, GREEN))),
                           colored("unexplained_rows", thresholds((None, GREEN), (1, RED)))]),
          24, 7)  # fmt: skip
    b.add(table("Quality flags per source month (rows)", sql("""
        SELECT to_char(source_month, 'YYYY-MM') AS month, negative_amount_rows,
               pickup_after_dropoff_rows, duplicate_rows, out_of_period_rows,
               implausible_speed_rows, implausible_distance_rows, unrealistic_duration_rows,
               zero_distance_rows, null_zone_rows, unknown_payment_rows, unknown_ratecode_rows,
               cross_month_rows, not_reported_rows, component_mismatch_rows
        FROM analytics.recon_bronze_silver ORDER BY source_month""")), 24, 7)
    b.add(series("Valid-trip rate by month", [prom("nyc_quality_month_valid_trip_rate",
                                                  "{{source_month}}")],
                 unit="percentunit", kind="bars"), 12, 8)  # fmt: skip
    b.add(series("Rows: file versus silver", [
        prom("nyc_quality_month_file_rows", "file {{source_month}}"),
        prom("nyc_quality_month_silver_rows", "silver {{source_month}}", ref="B")]), 12, 8)
    return b


def infrastructure() -> Board:
    b = with_links(Board(UIDS["infra"], "3. Infrastructure: host, containers, PostgreSQL",
                         "Memory, swap and CPU of the Docker host, each container, and the "
                         "warehouse database.", ["infrastructure"]))  # fmt: skip
    b.add(series("Host memory and swap", [
        prom("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "memory used"),
        prom("node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", "swap used", ref="B"),
        prom("node_memory_MemTotal_bytes", "memory total", ref="C")], unit="bytes"), 12, 8)
    b.add(series("Host CPU", [prom(
        '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))', "busy"),
        prom("rate(node_pressure_cpu_waiting_seconds_total[5m])", "CPU pressure (waiting)",
             ref="B")], unit="percentunit",
        description="CPU pressure: share of time tasks waited for a CPU (the 'soft lockup' "
                    "crashes of PostgreSQL happened under heavy pressure)."), 12, 8)  # fmt: skip
    b.add(series("Memory by container", [prom(
        'sum by (name) (container_memory_working_set_bytes{name=~"nyc-taxi-insight-hub-.*"})',
        "{{name}}")], unit="bytes", stack=True), 12, 9)  # fmt: skip
    b.add(series("CPU by container", [prom(
        'sum by (name) (rate(container_cpu_usage_seconds_total{name=~"nyc-taxi-insight-hub-.*"}[5m]))',
        "{{name}}")], unit="percentunit", stack=True), 12, 9)  # fmt: skip
    b.section("PostgreSQL")
    b.add(series("Connections by database", [prom(
        "sum by (datname) (pg_stat_database_numbackends)", "{{datname}}")]), 8, 7)
    b.add(series("Cache hit ratio (warehouse)", [prom(
        'sum(rate(pg_stat_database_blks_hit{datname="warehouse"}[5m])) / '
        '(sum(rate(pg_stat_database_blks_hit{datname="warehouse"}[5m])) + '
        'sum(rate(pg_stat_database_blks_read{datname="warehouse"}[5m])))', "hit ratio")],
        unit="percentunit",
        description="Low ratio: queries read the disk (the BI views are prewarmed after "
                    "each publication)."), 8, 7)  # fmt: skip
    b.add(series("Database size", [prom("pg_database_size_bytes", "{{datname}}")],
                 unit="bytes"), 8, 7)  # fmt: skip
    b.add(logs("PostgreSQL errors and restarts",
               '{service="postgres"} |~ "(?i)error|fatal|panic|terminated|shut ?down"'), 24, 7)
    return b


def bi() -> Board:
    b = with_links(Board(UIDS["bi"], "4. BI: Superset and its cache",
                         "Superset activity (StatsD), the Redis cache and the refresh of the "
                         "dashboards after each publication.", ["bi"]))  # fmt: skip
    b.add(series("Superset events per minute", [prom(
        'sum by (__name__) (rate({__name__=~"superset_.*_count|superset_.*_total"}[5m])) * 60',
        "{{__name__}}")], description="Dashboard loads, chart queries, API calls."), 12, 8)
    b.add(series("Cache hit ratio (Redis)", [prom(
        "rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + "
        "rate(redis_keyspace_misses_total[5m]))", "hit ratio")], unit="percentunit",
        description="Charts served from the 24 h cache rather than PostgreSQL."), 12, 8)
    b.add(series("Redis memory", [prom("redis_memory_used_bytes", "used"),
                                  prom("redis_memory_max_bytes", "limit", ref="B")],
                 unit="bytes"), 12, 7)  # fmt: skip
    b.add(table("Dashboard refresh runs (Airflow)", sql("""
        SELECT run_id, status, published, started_at, finished_at, message
        FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 10"""),
                description="Each published run refreshes Superset (task refresh_dashboards)."),
          12, 7)  # fmt: skip
    b.add(logs("Superset errors", '{service="superset"} |~ "(?i)error|timeout|exception"'), 24, 7)
    return b


def assistant() -> Board:
    b = with_links(Board(UIDS["ai"], "5. AI assistant: answers, steps, guardrails",
                         "Every question is a trace (one span per step) and a row of the audit "
                         "log. Where does the time go, and which safeguard acted?", ["ai"]))
    b.add(stat("Answers (24 h)", prom("sum(nyc_ai_audit_answers_24h) or vector(0)", instant=True),
               description="Exact count from the audit log (every answer is a row), not an "
                           "estimate from a counter."), 6, 4)  # fmt: skip
    b.add(stat("Median answer time (1 h)", prom(
        "histogram_quantile(0.5, sum by (le) (rate(assistant_answer_seconds_bucket[1h])))",
        instant=True), unit="s", steps=thresholds((None, GREEN), (180, YELLOW), (300, RED)),
        no_value="no question (1 h)"), 6, 4)  # fmt: skip
    b.add(stat("Narratives replaced (24 h)", prom(
        count('sum(increase(assistant_narrative_checks_total{check="replaced"}[24h])) '
              "or vector(0)"), instant=True),
        steps=thresholds((None, GREEN), (3, YELLOW))), 6, 4)  # fmt: skip
    b.add(stat("Plans adjusted or repaired (24 h)", prom(
        count("sum(increase(assistant_plan_changes_total[24h])) or vector(0)"), instant=True),
        steps=thresholds((None, BLUE))), 6, 4)  # fmt: skip
    b.add(series("Answers by status", [prom(
        count("sum by (status) (increase(assistant_answers_total[15m]))"), "{{status}}")],
        stack=True, kind="bars",
        description="answered, rejected (guardrail or validator), unsupported, clarify, "
                    "model_unavailable, query_failed."), 12, 8)  # fmt: skip
    b.add(series("Time per step (median)", [prom(
        "histogram_quantile(0.5, sum by (le, step) (rate(assistant_step_seconds_bucket[1h])))",
        "{{step}}")], unit="s",
        description="plan and narrate are model calls; validate, execute and provenance are "
                    "code and PostgreSQL."), 12, 8)  # fmt: skip
    b.add(series("Model tokens per step", [prom(
        "sum by (step, kind) (increase(assistant_llm_tokens_total[1h]))", "{{step}} {{kind}}")],
        stack=True, kind="bars",
        description="'read' excludes the tokens the model took from its cache: a small "
                    "number on a long prompt means the prompt cache works."), 12, 8)
    b.add(series("Safeguards that acted", [
        prom('sum(increase(assistant_narrative_checks_total{check="replaced"}[1h]))',
             "narrative replaced"),
        prom('sum by (kind) (increase(assistant_plan_changes_total[1h]))', "plan {{kind}}",
             ref="B")], stack=True, kind="bars"), 12, 8)  # fmt: skip
    b.add(table("Last answers (audit log): open a trace from its id", sql("""
        SELECT created_at, verdict, left(question, 70) AS question, duration_ms / 1000 AS seconds,
               narrative_check, trace_id, left(reasons::text, 120) AS reasons
        FROM ops.ai_audit_log ORDER BY event_id DESC LIMIT 20"""),
                overrides=[{"matcher": {"id": "byName", "options": "trace_id"},
                            "properties": [{"id": "links", "value": [{
                                "title": "Open the trace",
                                "url": "/explore?left=" + json.dumps({
                                    "datasource": "tempo",
                                    "queries": [{"refId": "A", "queryType": "traceql",
                                                 "query": "${__value.raw}"}]})}]}]}]),
          24, 9)  # fmt: skip
    b.add(logs("Assistant log (one line per answer, with its trace)",
               '{service="api"} |= "answer status="'), 24, 7)
    b.add({"type": "traces", "title": "Recent traces of the assistant", "datasource": TEMPO,
           "targets": [{"datasource": TEMPO, "queryType": "traceqlSearch", "refId": "A",
                        "query": '{resource.service.name="nyc-taxi-assistant"}',
                        "limit": 20}]}, 24, 8)  # fmt: skip
    return b


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for build in (overview, pipeline, quality, infrastructure, bi, assistant):
        board = build()
        path = OUT / f"{board.uid}.json"
        # Same bytes on every system, so the CI can check the files are generated.
        path.write_text(json.dumps(board.json(), indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"{path.name}: {len(board.panels)} panels")


if __name__ == "__main__":
    main()
