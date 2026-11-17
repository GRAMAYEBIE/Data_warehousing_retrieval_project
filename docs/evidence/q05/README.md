# Q5 evidence: orchestration, reliability and observability

All runs below are real runs of `monthly_yellow_pipeline` on the development machine,
17 November 2026 (Airflow 3.3.1, LocalExecutor, astronomer-cosmos 1.16.0).

| File | Content |
|---|---|
| `airflow_runs_and_tasks.txt` | Every run with its state and duration, and every task with state, tries and duration |
| `run_success_and_recovery_2025_01.log` | Successful run with a failure and its recovery (logs of the non-dbt tasks, every attempt) |
| `safe_rerun_nothing_new_2025_01.log` | Safe re-run of the same month: nothing reloaded, nothing rebuilt |
| `failed_run_2025_01.log` | Failed run: the outcome task records and reports the failure |
| `ops_runs_signals_publications.txt` | `ops.pipeline_runs`, `ops.pipeline_signals`, dbt test results per run, `ops.publications` |

## (i) Successful run: `run_2025_01_attempt2`

Month 2025-01, `force=false`. The source file was unchanged, so landing ended as
`skipped_unchanged` and bronze was not reloaded. Nothing had been published yet, so the
dbt build ran, 69 dbt tests passed and were recorded in `ops.dbt_test_results`, the five
operational signals were `ok`, the quality gate opened and 14 tables were published to
`analytics` in one transaction. Outcome: `published`.

| Signal | Value | Status |
|---|---|---|
| freshness_days | 0.54 days | ok |
| volume_change_vs_prior_month | −5.27 % | ok |
| rejected_row_rate | 8.56 % | ok |
| late_data_rate | 0.0006 % | ok |
| dbt_test_pass_rate | 100 % (69/69) | ok |

## (ii) Recovery after a failure (same run)

`measure_signals` failed on its first attempt with
`TypeError: can't subtract offset-naive and offset-aware datetimes`: the freshness signal
compared the container clock (no time zone) with a PostgreSQL `timestamptz`.

Response:

1. The code was fixed (time-zone aware comparison) and a regression test was added
   (`airflow/tests/test_ops.py::test_freshness_signal_accepts_database_timestamps_with_time_zone`).
2. Airflow retried the task automatically (attempt 2, 11:10): it passed with the fix.
3. The task was also cleared through the Airflow REST API (attempt 3, 11:12), which is
   the documented recovery path. It passed again and wrote the same five signals: the
   write is an upsert on `(run_id, signal_name)`, so a repeated attempt never duplicates.
4. The run continued from that task: the two hours of dbt work were not redone.
   `quality_gate_and_publish` and `record_outcome_and_notify` then succeeded.

Observed limitation: the automatic retry started about 24 minutes after the failure
instead of the configured 5 minutes. The cause was not identified; the configuration was
also corrected (`retry_exponential_backoff` is a multiplier in Airflow 3.3, so `True`
meant 1.0, no backoff; it is now `2.0`).

## (iii) Safe re-run: `rerun_2025_01_nothing_new`

Same month again, `force=false`. Landing: `source unchanged (ETag ...): nothing to do`
(a new `skipped_unchanged` row in the ingestion manifest). Load: the batch is already in
bronze. `anything_to_publish`: every loaded batch is already in the last publication, so
the 48 build tasks were skipped. Outcome: `nothing_new`, 1 minute 21 seconds, no data
changed anywhere.

## Infrastructure failure during a build: `load_2025_02`

February 2025 was loaded through Airflow: `check_source`, `land_to_rustfs` (93 s) and
`load_bronze` (342 s, 3,577,543 rows) succeeded. The silver build then failed three times:

1. Attempt 1 was rescheduled: the task worker needed more than 30 s to import the DAG
   file on the saturated host (`DagBag import timeout`).
2. Attempt 2 was stopped after 50 minutes: the scheduler heartbeat stalled for 137 s and
   the running task was considered lost (`task_instance_heartbeat_timeout` 300 s).
3. Attempt 3 failed when a PostgreSQL backend exited (code 2, no error message) and the
   server restarted to recover (`the database system is in recovery mode`). At that
   moment the Windows host had 0.43 GB of free memory out of 7.9 GB, CPU at 98 %.

What the platform did: every write of the build is in a transaction, so nothing partial
was kept. After the failure, bronze held February, silver and gold still held only
December and January, and `analytics` still showed the January publication
(`run_2025_01_attempt2`): users never saw an incomplete state.

Changes made after this incident:

| Setting | Before | After |
|---|---|---|
| Pipeline tasks at the same time | 2 | 1 (`PIPELINE_MAX_ACTIVE_TASKS`) |
| `AIRFLOW__CORE__DAGBAG_IMPORT_TIMEOUT` | 30 s | 120 s |
| `AIRFLOW__SCHEDULER__TASK_INSTANCE_HEARTBEAT_TIMEOUT` | 300 s | 1200 s |
| `AIRFLOW__SCHEDULER__SCHEDULER_HEALTH_CHECK_THRESHOLD` | 30 s | 120 s |
| Silver build memory | `work_mem` 128 MB, 2 parallel workers | 64 MB, 1 parallel worker |

The same run also showed an ordering defect: the reconciliation test read the manifest
source and the silver models, and Cosmos attached it to the source, so it ran before
silver contained February and failed. The test now reads `recon_bronze_silver` only, so
it runs after silver is built (same check, right moment).

Conclusion: the full pipeline needs more resources than the 4 GB Docker share of an
8 GB laptop when other applications are open. Historical months are better loaded on a
larger machine (or with other applications closed); the code does not change.

## Failure mode: `first_run_2025_01`

The first task could not reach the Airflow execution API within 5 seconds while the DAG
processor was busy (`httpcore.ReadTimeout`). Every downstream task became
`upstream_failed`, nothing was published, and `record_outcome_and_notify` (trigger rule
`all_done`) still ran, recorded the outcome `failed` and logged it at error level. Fix:
`AIRFLOW__WORKERS__EXECUTION_API_TIMEOUT=60` and DAG re-parsing every 5 minutes instead of
30 seconds.
