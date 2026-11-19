# Metric parity: same metric, same value on every surface (Q6.4)

Generated 2026-11-18 23:33 UTC by `tests/consistency/metric_parity.py`.
Published layer: run `load_2025_02`, published 2026-11-18 11:58 UTC.

- **dbt / MetricFlow**: `mf query --group-by metric_time__month` on `gold.fct_trip`.
- **Published SQL**: the metric's `sql_expression` from the dbt YAML over the
  `analytics` aggregates, run as `ai_reader` (the AI assistant's read-only role).
- **Superset**: the chart data API on the certified dataset (`trips_daily`, or
  `trips_hourly` for trips_per_active_hour), with the metric Superset holds, copied
  from the same YAML by metrics-sync. Superset shows complete months only.

Tolerance: relative difference at most 1E-9. Result: **40 of 40 values match**.

Months marked *partial* have no source file loaded: they only hold valid trips
picked up a few hours before or after a loaded month (cross-month rows, counted
on their real pickup date). Dashboards and the AI assistant show complete months
only; the rows are kept here to prove both surfaces treat them identically.

| Pickup month | Metric | dbt / MetricFlow | Published SQL (AI role) | Superset chart | Result |
|---|---|---|---|---|---|
| 2024-11 (partial) | `trips` | 26 | 26 | not shown (partial month) | match |
| 2024-11 (partial) | `total_revenue` | 735.62 | 735.62 | not shown (partial month) | match |
| 2024-11 (partial) | `avg_fare` | 18.338462 | 18.338462 | not shown (partial month) | match |
| 2024-11 (partial) | `tip_rate` | 0.239891 | 0.239891 | not shown (partial month) | match |
| 2024-11 (partial) | `valid_trip_rate` | 1 | 1 | not shown (partial month) | match |
| 2024-11 (partial) | `trips_per_active_hour` | 13 | 13 | not shown (partial month) | match |
| 2024-11 (partial) | `congestion_fee_revenue` | - | - | not shown (partial month) | match (no value on either surface) |
| 2024-11 (partial) | `est_co2_kg` | 34.416 | 34.416 | not shown (partial month) | match |
| 2024-12 | `trips` | 3,435,475 | 3,435,475 | 3,435,475 | match |
| 2024-12 | `total_revenue` | 99,175,664.01 | 99,175,664.01 | 99,175,664.01 | match |
| 2024-12 | `avg_fare` | 19.857628 | 19.857628 | 19.857628 | match |
| 2024-12 | `tip_rate` | 0.229079 | 0.229079 | 0.229079 | match |
| 2024-12 | `valid_trip_rate` | 0.936516 | 0.936516 | 0.936516 | match |
| 2024-12 | `trips_per_active_hour` | 4,617.573925 | 4,617.573925 | 4,617.573925 | match |
| 2024-12 | `congestion_fee_revenue` | 0 | 0 | 0 | match |
| 2024-12 | `est_co2_kg` | 4,420,130.644 | 4,420,130.644 | 4,420,130.644 | match |
| 2025-01 | `trips` | 3,177,899 | 3,177,899 | 3,177,899 | match |
| 2025-01 | `total_revenue` | 84,627,384.68 | 84,627,384.68 | 84,627,384.68 | match |
| 2025-01 | `avg_fare` | 17.727939 | 17.727939 | 17.727939 | match |
| 2025-01 | `tip_rate` | 0.238392 | 0.238392 | 0.238392 | match |
| 2025-01 | `valid_trip_rate` | 0.914441 | 0.914441 | 0.914441 | match |
| 2025-01 | `trips_per_active_hour` | 4,271.369624 | 4,271.369624 | 4,271.369624 | match |
| 2025-01 | `congestion_fee_revenue` | 1,592,638.5 | 1,592,638.5 | 1,592,638.5 | match |
| 2025-01 | `est_co2_kg` | 3,893,591.892 | 3,893,591.892 | 3,893,591.892 | match |
| 2025-02 | `trips` | 3,237,672 | 3,237,672 | 3,237,672 | match |
| 2025-02 | `total_revenue` | 84,930,446.6 | 84,930,446.6 | 84,930,446.6 | match |
| 2025-02 | `avg_fare` | 17.624646 | 17.624646 | 17.624646 | match |
| 2025-02 | `tip_rate` | 0.237669 | 0.237669 | 0.237669 | match |
| 2025-02 | `valid_trip_rate` | 0.905006 | 0.905006 | 0.905006 | match |
| 2025-02 | `trips_per_active_hour` | 4,817.964286 | 4,817.964286 | 4,817.964286 | match |
| 2025-02 | `congestion_fee_revenue` | 1,824,050.5 | 1,824,050.5 | 1,824,050.5 | match |
| 2025-02 | `est_co2_kg` | 3,918,506.524 | 3,918,506.524 | 3,918,506.524 | match |
| 2025-03 (partial) | `trips` | 1 | 1 | not shown (partial month) | match |
| 2025-03 (partial) | `total_revenue` | 34.02 | 34.02 | not shown (partial month) | match |
| 2025-03 (partial) | `avg_fare` | 22.6 | 22.6 | not shown (partial month) | match |
| 2025-03 (partial) | `tip_rate` | 0.250885 | 0.250885 | not shown (partial month) | match |
| 2025-03 (partial) | `valid_trip_rate` | 0.333333 | 0.333333 | not shown (partial month) | match |
| 2025-03 (partial) | `trips_per_active_hour` | 1 | 1 | not shown (partial month) | match |
| 2025-03 (partial) | `congestion_fee_revenue` | 0.75 | 0.75 | not shown (partial month) | match |
| 2025-03 (partial) | `est_co2_kg` | 1.296 | 1.296 | not shown (partial month) | match |

## Fourth surface: the AI assistant (2026-11-19 15:00 UTC)

The question is asked in plain English to the running assistant (qwen2.5:3b, prompt
v3, retrieval on) by `tests/consistency/assistant_parity.py`; its value is compared with
the MetricFlow value of the table above (relative tolerance 1e-6; MetricFlow rounds the
average to six decimals, the assistant returns the database value unrounded).

| Month | Metric | Question | MetricFlow | Assistant | Plan and months | Result |
|---|---|---|---|---|---|---|
| 2025-01 | `trips` | How many trips did we have in January 2025? | 3177899 | 3177899 | ['trips'] ['2025-01'] | match |
| 2025-01 | `total_revenue` | What was the total revenue in January 2025? | 84627384.68 | 84627384.68 | ['total_revenue'] ['2025-01'] | match |
| 2025-01 | `avg_fare` | What was the average fare in January 2025? | 17.727939 | 17.7279391384055944 | ['avg_fare'] ['2025-01'] | match |

3/3 match: the same governed metric returns the same value in MetricFlow (dbt), the
published SQL, Superset and the AI assistant.
