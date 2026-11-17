"""Monthly NYC Yellow Taxi pipeline.

check source -> land in RustFS -> load bronze -> anything new? -> dbt build (Cosmos,
one task per model, tests after each model) -> operational signals -> quality gate +
atomic publication to analytics -> record outcome and notify.

Safety:
  * max_active_runs=1: two monthly runs never overlap.
  * Every step is idempotent: landing skips an unchanged file, bronze replaces the month
    partition in one transaction, dbt rebuilds only months whose batch changed, and the
    publication swaps tables in one transaction.
  * After a partial failure, clear the failed task: the steps before it are not redone,
    and analytics keeps the previous publication until a run passes the gate.

Manual run / backfill: trigger with {"month": "2025-03", "force": false}.
Without "month", a scheduled run targets the month two months before the run date
(TLC publishes about two months late).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
from airflow.sdk import DAG, Param, get_current_context
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import LoadMode, SourceRenderingBehavior, TestBehavior

from nyc_taxi_ops import dbt_results, outcome, publish, signals

DAG_ID = "monthly_yellow_pipeline"
DBT_PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt"))
WAREHOUSE_CONN = "warehouse_publisher"  # role publisher: reads gold/ops, writes analytics
INGEST = "/opt/ingestion_venv/bin/python -m ingestion.cli"
MONTH = "{{ ti.xcom_pull(task_ids='resolve_run')['month'] }}"
FORCE_FLAG = "{{ '--force' if ti.xcom_pull(task_ids='resolve_run')['force'] else '' }}"

# Ingestion runs as the loader role; the variables are set on the Airflow containers.
INGEST_ENV = {
    "PGHOST": os.environ.get("INGEST_PGHOST", "postgres"),
    "PGPORT": os.environ.get("INGEST_PGPORT", "5432"),
    "PGDATABASE": os.environ.get("INGEST_PGDATABASE", "warehouse"),
    "PGUSER": os.environ.get("INGEST_PGUSER", "loader"),
    "PGPASSWORD": os.environ.get("INGEST_PGPASSWORD", ""),
}


def _connection():
    return PostgresHook(postgres_conn_id=WAREHOUSE_CONN).get_conn()


def _target_month(params: dict, run_after: datetime) -> date:
    if params.get("month"):
        year, month = str(params["month"]).split("-")
        return date(int(year), int(month), 1)
    months = run_after.year * 12 + (run_after.month - 1) - 2  # two months before the run
    return date(months // 12, months % 12 + 1, 1)


def resolve_run(params: dict, dag_run, **_) -> dict:
    run_after = getattr(dag_run, "run_after", None) or datetime.now()
    month = _target_month(params, run_after)
    force = bool(params.get("force"))
    conn = _connection()
    try:
        outcome.start_run(conn, dag_run.run_id, DAG_ID, month, force)
    finally:
        conn.close()
    return {"month": f"{month:%Y-%m}", "source_month": month.isoformat(), "force": force}


def anything_to_publish(dag_run, ti, **_) -> bool:
    """Continue only when a loaded batch is not in the last publication (or force)."""
    run = ti.xcom_pull(task_ids="resolve_run")
    conn = _connection()
    try:
        loaded = publish.latest_loaded_batches(conn)
        published = publish.latest_published_batches(conn)
        if run["force"] or loaded != published:
            changed = sorted(m for m in loaded if loaded[m] != published.get(m))
            print(f"new or changed batches to build and publish: {changed or 'forced run'}")
            return True
        outcome.mark(conn, dag_run.run_id, "nothing_new", "every loaded batch is already published")
        print("every loaded batch is already published: nothing to build")
        return False
    finally:
        conn.close()


def record_dbt_results(project_dir: str, *args, **kwargs) -> None:
    """Cosmos callback: store the test results of the dbt command that just ran."""
    rows = dbt_results.test_results(dbt_results.read_run_results(project_dir))
    if not rows:
        return
    # Cosmos passes the task context as a keyword argument (cosmos/operators/local.py).
    context = kwargs.get("context") or get_current_context()
    run_id = context["dag_run"].run_id
    conn = _connection()
    try:
        dbt_results.store(conn, run_id, rows)
    finally:
        conn.close()


def measure_signals(dag_run, ti, **_) -> list[dict]:
    run = ti.xcom_pull(task_ids="resolve_run")
    conn = _connection()
    try:
        # Time-zone aware: PostgreSQL returns timestamptz values.
        measured = signals.measure(
            conn, dag_run.run_id, date.fromisoformat(run["source_month"]), datetime.now(UTC)
        )
        signals.record(conn, dag_run.run_id, date.fromisoformat(run["source_month"]), measured)
    finally:
        conn.close()
    return [{"name": s.name, "status": s.status, "value": s.value} for s in measured]


def gate_and_publish(dag_run, **_) -> dict:
    conn = _connection()
    try:
        try:
            publish.check_gate(conn, dag_run.run_id)
        except publish.GateClosed as closed:
            conn.rollback()
            outcome.mark(conn, dag_run.run_id, "failed", f"quality gate closed: {closed}")
            raise
        return publish.publish(conn, dag_run.run_id)
    finally:
        conn.close()


def finish(dag_run, **_) -> dict:
    conn = _connection()
    try:
        summary = outcome.finish_run(conn, dag_run.run_id)
    finally:
        conn.close()
    outcome.notify(summary)
    if summary["status"] == "failed":
        raise RuntimeError(f"pipeline run failed: {summary.get('message') or 'see task logs'}")
    return summary


default_args = {
    "owner": "AYEBIE GRAM MESCHAC",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    # Airflow 3.3: a multiplier (True would mean 1.0, no backoff): 5, 10, 20... minutes.
    "retry_exponential_backoff": 2.0,
    "max_retry_delay": timedelta(minutes=30),
}

with DAG(
    dag_id=DAG_ID,
    description="Monthly Yellow Taxi ingestion, dbt build, quality gate and publication",
    # Production: "0 6 3 * *" (3rd of each month, 06:00). Empty: manual runs only, used
    # while the historical months are loaded one by one (see .env.example).
    schedule=os.environ.get("PIPELINE_SCHEDULE") or None,
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    # One task at a time on the 4-CPU / 4 GB development machine: two heavy dbt tasks in
    # parallel slowed each other until Airflow heartbeats stalled. Raise on a larger host.
    max_active_tasks=int(os.environ.get("PIPELINE_MAX_ACTIVE_TASKS", "1")),
    dagrun_timeout=timedelta(hours=6),
    default_args=default_args,
    params={
        "month": Param(
            "",
            type="string",
            pattern=r"^(\d{4}-(0[1-9]|1[0-2]))?$",
            description="Source month YYYY-MM. Empty: two months before the run date.",
        ),
        "force": Param(False, type="boolean", description="Reload even if the file is unchanged."),
    },
    tags=["nyc-taxi", "monthly", "dbt"],
    doc_md=__doc__,
) as dag:
    resolve = PythonOperator(task_id="resolve_run", python_callable=resolve_run, retries=0)

    check_source = BashOperator(
        task_id="check_source",
        bash_command=f"{INGEST} check --month {MONTH}",
        env=INGEST_ENV,
        append_env=True,
        # The file of a month may not be published yet: wait and try again.
        retries=4,
        retry_delay=timedelta(hours=6),
        retry_exponential_backoff=1.0,
    )

    land = BashOperator(
        task_id="land_to_rustfs",
        bash_command=f"{INGEST} land --month {MONTH} {FORCE_FLAG}",
        env=INGEST_ENV,
        append_env=True,
    )

    load_bronze = BashOperator(
        task_id="load_bronze",
        bash_command=f"{INGEST} load --month {MONTH}",
        env=INGEST_ENV,
        append_env=True,
        execution_timeout=timedelta(hours=1),
    )

    decide = ShortCircuitOperator(
        task_id="anything_to_publish",
        python_callable=anything_to_publish,
        # Skip the build steps only; finish (all_done) still runs and reports "nothing_new".
        ignore_downstream_trigger_rules=False,
    )

    dbt_build = DbtTaskGroup(
        group_id="dbt_build",
        project_config=ProjectConfig(
            dbt_project_path=DBT_PROJECT_DIR,
            manifest_path=DBT_PROJECT_DIR / "target" / "manifest.json",
        ),
        profile_config=ProfileConfig(
            profile_name="nyc_taxi",
            target_name="dev",
            profiles_yml_filepath=DBT_PROJECT_DIR / "profiles.yml",
        ),
        execution_config=ExecutionConfig(dbt_executable_path="/opt/dbt_venv/bin/dbt"),
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            test_behavior=TestBehavior.AFTER_EACH,
            # Sources with tests or freshness become tasks too: the bronze source tests
            # and the freshness check of the ingestion manifest run before any model.
            source_rendering_behavior=SourceRenderingBehavior.WITH_TESTS_OR_FRESHNESS,
        ),
        operator_args={
            # dbt packages are installed once by airflow-init; each task copies them
            # instead of downloading them again.
            "install_deps": False,
            "copy_dbt_packages": True,
            "callback": record_dbt_results,
            "execution_timeout": timedelta(hours=2),
            "retries": 1,
        },
    )

    measure = PythonOperator(task_id="measure_signals", python_callable=measure_signals)

    publish_task = PythonOperator(
        task_id="quality_gate_and_publish", python_callable=gate_and_publish, retries=1
    )

    report = PythonOperator(
        task_id="record_outcome_and_notify",
        python_callable=finish,
        trigger_rule="all_done",
        retries=1,
    )

    # When "anything_to_publish" short-circuits, the build steps are skipped and
    # record_outcome_and_notify (trigger rule all_done) still reports "nothing_new".
    resolve >> check_source >> land >> load_bronze >> decide >> dbt_build
    dbt_build >> measure >> publish_task >> report
