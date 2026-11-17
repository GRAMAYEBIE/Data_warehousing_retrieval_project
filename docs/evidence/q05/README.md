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

## Failure mode: `first_run_2025_01`

The first task could not reach the Airflow execution API within 5 seconds while the DAG
processor was busy (`httpcore.ReadTimeout`). Every downstream task became
`upstream_failed`, nothing was published, and `record_outcome_and_notify` (trigger rule
`all_done`) still ran, recorded the outcome `failed` and logged it at error level. Fix:
`AIRFLOW__WORKERS__EXECUTION_API_TIMEOUT=60` and DAG re-parsing every 5 minutes instead of
30 seconds.
