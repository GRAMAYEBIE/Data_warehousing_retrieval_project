# NYC Taxi Insight Hub

End-to-end data warehouse, BI and AI analytics platform on NYC TLC Yellow Taxi trip records.
Final project for **DS6102 Data Warehousing and Information Retrieval** (Academic City University, lecturer: Jeremiah Ishaya).

- Author: AYEBIE GRAM MESCHAC
- Project window: 16 to 30 November 2026 (15 days)
- Full exam paper: `docs/exam/DS6102_sujet.pdf`

  
This document is the project reference: what is built, how to run it, and the design
decisions for the parts still to build. Sections marked **(planned)** describe a design
that is not implemented yet.

---

## 1. Status

| Wave | Scope | Status |
|---|---|---|
| 1 | Docker Compose core, warehouse schemas and roles, landing zone, idempotent ingestion, bronze layer, manifest | **Built and verified** |
| 2 | dbt: silver, quality flags, star schema, aggregates, tests, reconciliation | Planned |
| 3 | Airflow orchestration, publication gate, operational signals | Planned |
| 4 | Semantic layer, Superset, six dashboards | Planned |
| 5 | AI assistant: API, web interface, evaluation pack | Planned |
| 6 | Extensions: Prometheus/Grafana, Kafka, MLflow | Planned, optional |

Loaded so far: `2024-12` (3,668,371 rows) and `2025-01` (3,475,226 rows), plus the 265 taxi zones.

---

## 2. The problem

MetroMove Analytics supports the New York City taxi ecosystem. Operations leaders, city
planners and commercial analysts receive monthly trip files but cannot easily tell whether
demand is changing, which zones need attention, what drives revenue, or whether an unusual
fare is a data problem or a real event.

NYC Taxi Insight Hub is the first near-production version of one trusted platform: it
ingests Yellow Taxi records, produces a trusted gold layer, powers six strategic dashboards
and provides a safe AI analytics assistant. Every reported number must be traceable from the
raw trip file through bronze, silver and gold, to the metric definition and the final chart
or AI answer.

### Marks (100)

| Q | Marks | Topic | Main deliverable |
|---|---|---|---|
| Q1 | 7 | Problem and success measures | `docs/proposal.md` (1–2 pages) |
| Q2 | 8 | Source, ingestion, bronze | `ingestion/`, manifest, run / re-run / failure evidence |
| Q3 | 10 | Medallion and data quality | silver, flags, bronze → silver reconciliation |
| Q4 | 10 | Star schema and dbt | `fct_trip`, dimensions, tests, dbt docs, macros |
| Q5 | 8 | Airflow, reliability, observability | DAG, success / re-run logs, 3 operational signals |
| Q6 | 8 | Semantic layer (12 metrics) | MetricFlow YAML, 3-surface reconciliation |
| Q7 | 8 | Superset | certified datasets, RLS, drill-down, insights |
| Q8 | 10 | AI report and dashboard builder | `ReportRequest`, draft via Superset API, confirmation |
| Q9 | 10 | Natural-language questions on gold | multi-turn, guardrails, provenance, 3 prompt variants |
| Q10 | 6 | Evaluation and testing | 15+ cases, end-to-end smoke test, 1 analysed failure |
| Q11 | 5 | Security and governance | SQL roles, `.env.example`, governance note |
| Q12 | 5 | Docker and project quality | one-command startup, health checks |
| Q13 | 5 | Six strategic dashboards | every chart answers a question, "so what?" insight |

Q3, Q4, Q8 and Q9 carry 40 marks: they have priority after the base platform.

---

## 3. Quick start

Requirements: Docker with Docker Compose. Tested with Docker 29 and Compose v5 on Windows 11.

```bash
# 1. Configuration: copy the template and replace every "change_me" value
cp .env.example .env

# 2. Start the core services (PostgreSQL, RustFS) and check their health
docker compose --profile core up -d
docker compose --profile core ps

# 3. Load the taxi zone lookup
docker compose --profile core --profile tools run --rm ingestion zones

# 4. Load one month (the demonstration month is 2025-01)
docker compose --profile core --profile tools run --rm ingestion yellow --month 2025-01

# 5. Run it again: the source is unchanged, nothing is reloaded
docker compose --profile core --profile tools run --rm ingestion yellow --month 2025-01

# 6. Force a reload of the month (replaces the bronze partition)
docker compose --profile core --profile tools run --rm ingestion yellow --month 2025-01 --force
```

The same commands exist as `make up`, `make zones`, `make ingest MONTH=2025-01`,
`make ingest-force MONTH=2025-01`, `make test-ingestion`, `make lint-ingestion`.

Exit codes of the ingestion command: `0` loaded or skipped, `2` source file not available,
`3` file or contract rejected, `1` any other failure.

The init scripts in `infra/postgres/init/` run only when the PostgreSQL volume is created
for the first time.

### Evidence of the three required behaviours (Q2)

| Behaviour | Result | Log |
|---|---|---|
| Successful run | `2024-12` loaded, 3,668,371 rows in the file and in bronze | `docs/evidence/q02/run_2024-12_contract_v2024.log` |
| Safe re-run | `2025-01` → `skipped_unchanged` in 4 seconds | `docs/evidence/q02/rerun_2025-01_skipped_unchanged.log` |
| Failure mode | `2027-01` → `failed`, HTTP 403 recorded in the manifest, exit code 2 | `docs/evidence/q02/failure_2027-01_source_missing.log` |
| Forced re-run | `2025-01` reloaded with `--force` | `docs/evidence/q02/forced_rerun_2025-01.log` |

### Local resources

The development machine has 8 GB of RAM with 4 GB given to Docker. This is enough for the
core profile. One month takes about 1.2 GB in bronze and 5 to 10 minutes to load. Thirteen
months are projected at about 15 GB in bronze and 40 to 45 GB with silver and gold.
A demonstration mode (`DEMO_MODE=true`) will limit the platform to one month and a small
LLM (`qwen2.5:3b`).

---

## 4. Architecture

```
SOURCES                    LANDING (RustFS S3)            ORCHESTRATION
TLC Yellow Parquet   ──►   raw/yellow/year=/month=/  ◄──  Airflow 3 + Cosmos
 (2024-12 → 2025-12)       manifests/                     monthly DAG, targets M-2
Zone lookup + shapefile    quarantine/                    max_active_runs=1
US/NY public holidays
                                  │ COPY
                                  ▼
POSTGRESQL 16 — database `warehouse` ────────────────────────────────────
  bronze    yellow_trips_raw (one partition per month, immutable)
     │ dbt staging + intermediate
     ▼
  silver    typed trips + flags + status      ◄── BLOCKING TESTS HERE
     │ dbt marts
     ▼
  gold      fct_trip + dimensions + agg_* (sums and counts only)
     │
     │  ═══ PUBLICATION GATE: only if the whole dbt build is green ═══
     ▼
  analytics materialized views = published copy of the gold agg_* tables
  semantic  metric_catalog (generated from the dbt metric YAML)
  ops       ingestion_manifest, pipeline_runs, pipeline_signals, ai_audit_log
─────────────────────────────────────────────────────────────────────────
        │ superset_reader                    │ ai_reader (read-only, 10 s)
        ▼                                    ▼
  Superset + Redis                    FastAPI ──► Ollama (qwen2.5)
  6 certified dashboards                 │  └──► Superset REST API (drafts)
                                         ▼
                                  React UI (Vite)   [plan B: Streamlit]
```

One PostgreSQL server holds three separate databases: `warehouse` (business data),
`airflow_meta` and `superset_meta` (internal state of the tools).

Bronze, silver, gold and analytics are **schemas of the same database**. dbt stores and
moves nothing: it sends SQL that PostgreSQL executes. The only real data transfer is
Parquet file → bronze.

The landing zone is an S3-compatible object store that runs locally in Docker. It keeps the
original file untouched, so bronze can be rebuilt without downloading again and the received
file can be proven. Moving to a cloud object store only changes the endpoint in `.env`.

### Flow of one month

1. **Check**: `HEAD` request on the file of month **M-2** (TLC publishes with about two months of delay).
2. **Land**: download → validation (Parquet magic bytes, size, SHA-256) → RustFS `raw/yellow/year=YYYY/month=MM/` → row in `ops.ingestion_manifest`. Unchanged source ⇒ `skipped_unchanged`.
3. **Bronze**: the month partition is replaced, loaded with `COPY`.
4. **dbt build** through Cosmos: staging → silver → blocking tests → gold → aggregates → tests. A failing silver test makes dbt skip everything downstream, so gold is untouched.
5. **Publish**: `REFRESH MATERIALIZED VIEW CONCURRENTLY` on `analytics`, **only if step 4 is green**. Otherwise users keep the previous state and an alert is sent.
6. **metrics-sync**: metric YAML → certified Superset datasets + `semantic.metric_catalog`.
7. **Operational signals** written to `ops.pipeline_signals`; notification (log + webhook/email).

Steps 1 to 3 are built. Steps 4 to 7 are planned.

---

## 5. Architecture decisions

| Decision | Justification |
|---|---|
| **Publication gate** | Superset and the AI assistant read **only** `analytics` (materialized views), refreshed by a separate Airflow task when the whole `dbt build` is green. dbt tests a table *after* writing it: without this gate, a failed test would leave wrong numbers visible. |
| **Deterministic technical identifier** | `(source_month, file_row_number)` instead of a database sequence: keys are identical after a reload, and a trip can be traced back to its exact row in the raw file. |
| **Additive aggregates only** | Aggregate tables store sums and counts; averages and ratios are computed at read time. An average of averages is wrong. |
| **Each metric formula is written once** | In the `meta:` block of the dbt YAML. Superset and the AI assistant copy it through `metrics-sync`. This makes the Q6 consistency check verifiable. |
| **The AI only uses templates on `analytics`** | `ai_reader` has no right on gold. MetricFlow (which reads `fct_trip`) is the "dbt" surface of the consistency check, not the engine of the assistant. |
| **RustFS instead of MinIO** | The exam allows an equivalent S3-compatible store with a written justification (status of MinIO Community edition). The justification must be sourced before the final submission. Image pinned to `rustfs/rustfs:1.0.6`. |
| **React (Vite) front end, not Next.js** | Vite + TypeScript + Tailwind + TanStack Query + Recharts. Types generated from the FastAPI OpenAPI schema. **Plan B: Streamlit on the same API** if the front end is not ready at the end of day 12 (27 November). |
| **No DuckDB** | PostgreSQL is the required warehouse; a second engine would be a competing source of truth. |
| **Metric catalogue in the prompt, no RAG** | About 15 metrics fit in the prompt; the exam asks for a "compact semantic catalogue". |
| **AI audit log in PostgreSQL** | `ops.ai_audit_log` and prompts versioned in git replace Langfuse (which needs ClickHouse, Redis and S3). It provides the guardrail logs required by Q9. |
| **Kafka kept as an extension** | Not required; it shows the streaming vision. Provisional rows **never** enter `fct_trip` or governed metrics. |
| **Removed** | pgvector, Langfuse, Tempo/OpenTelemetry, PgBouncer, pgAdmin, Celery beat, NOAA weather, OpenMetadata, Traefik, Loki. |

---

## 6. Source contract

| Source | URL | Notes |
|---|---|---|
| Yellow Taxi Parquet | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{YYYY}-{MM}.parquet` | One file per month. **13 months: 2024-12 → 2025-12.** Fallback if loading is too slow: 2024-12 → 2025-06 (7 months). |
| Taxi Zone Lookup | `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv` | 265 zones; 264 and 265 are Unknown / N/A. |
| Zone shapefile | `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip` | For Superset maps (converted to GeoJSON). |
| US public holidays | Python library `holidays` (US + NY) → dbt seed | Documented external source; needed by Dashboard 2. |

**Publication**: TLC publishes monthly, generally with two months of delay, and does not
guarantee the accuracy of the data, which is provided by vendors. This is treated as a real
data-quality risk.

**Expected columns**: `VendorID, tpep_pickup_datetime, tpep_dropoff_datetime, passenger_count, trip_distance, RatecodeID, store_and_fwd_flag, PULocationID, DOLocationID, payment_type, fare_amount, extra, mta_tax, tip_amount, tolls_amount, improvement_surcharge, total_amount, congestion_surcharge, Airport_fee`, plus `cbd_congestion_fee` from 2025-01.

**Versioned contract**: `ingestion/contracts/yellow_v2024.yaml` (without `cbd_congestion_fee`)
and `yellow_v2025.yaml` (with it). The contract is chosen from the month of the file.
The step from 2024-12 to 2025-01 is a real schema change, verified in bronze: the column is
NULL for all 3,668,371 rows of 2024-12 and filled for all 3,475,226 rows of 2025-01.

**Schema drift detection**: the file schema is compared with the contract and a
`schema_hash` (SHA-256 of the sorted `name:type` list) is written to the manifest.

| Situation | Behaviour |
|---|---|
| Unknown new column | Loaded into `extra_columns` (JSONB), warning, drift report in the manifest |
| Optional column absent | Stored as NULL |
| Required column absent | Blocking failure, nothing is loaded |
| Wrong type family | Blocking failure, nothing is loaded |
| Different letter case (`Airport_fee` / `airport_fee`) | Names are lower-cased at ingestion |

**Time zone**: TLC timestamps are **New York local time without a time zone**. They are
stored as they are (`timestamp without time zone`) and never converted to UTC, otherwise
peak hours would shift. Days with a clock change have 23 or 25 hours, which has a marginal
effect on `trips_per_active_hour`.

**Reference codes** (to check against the official TLC data dictionary before fixing `accepted_values`):
- `payment_type`: 0 Flex Fare, 1 Credit card, 2 Cash, 3 No charge, 4 Dispute, 5 Unknown, 6 Voided.
- `RatecodeID`: 1 Standard, 2 JFK, 3 Newark, 4 Nassau/Westchester, 5 Negotiated, 6 Group ride, 99 Unknown.
- `VendorID`: 1 Creative Mobile Technologies, 2 Curb Mobility, 6 Myle Technologies, 7 Helix.

Licence: public data from NYC Open Data, to be cited in `docs/source_contract.md`.

### Operational behaviour (Q2.5)

| Event | What happens |
|---|---|
| File missing (HTTP 403/404) | Manifest status `failed` with the error, exit code 2, nothing changes in the warehouse |
| Month re-run, source unchanged | Same ETag and size (or same SHA-256) ⇒ `skipped_unchanged`, no reload |
| Month re-run, source changed or `--force` | New `batch_id`, the landing object and the bronze partition are replaced in one transaction |
| Source adds a column | See schema drift detection above |

---

## 7. Warehouse

PostgreSQL 16 with `pg_stat_statements`.

| Schema | Content | Written by |
|---|---|---|
| `bronze` | `yellow_trips_raw` (partitioned by `source_month`), `taxi_zone_raw` | `loader` |
| `silver` | typed, cleaned, flagged trips; validated zones; quarantine | `transformer` (dbt) |
| `gold` | `fct_trip` (partitioned by month), dimensions, `agg_*` | `transformer` |
| `analytics` | published materialized views (copy of `agg_*`) and operational views | publication task |
| `semantic` | `metric_catalog` | metrics-sync |
| `ops` | `ingestion_manifest`, `pipeline_runs`, `pipeline_signals`, `reconciliation`, `ai_audit_log` | `loader` / Airflow / `ai_audit_writer` |

### Bronze: `bronze.yellow_trips_raw`

Source columns **as published** plus `source_month`, `file_row_number`, `batch_id`,
`source_file`, `ingested_at`, `schema_hash`, `extra_columns`.

- Key: `(source_month, file_row_number)`. `file_row_number` is **0-based**, the same index as pyarrow and pandas (`pq.read_table(f).slice(n, 1)`).
- `PARTITION BY LIST (source_month)`. Immutable: never updated; a re-run replaces the partition (`TRUNCATE` + `COPY` in a single transaction).
- Column names are the source names in lower case. Types are wide (`numeric` for codes, `double precision` for amounts, `timestamp` without time zone) so raw values stay recoverable.

Verified for both loaded months: row count, sum of `total_amount`, sum of `trip_distance`
and one sample row are identical between the landed Parquet file and bronze.

### Manifest: `ops.ingestion_manifest`

One row per ingestion attempt: `batch_id, dataset, source_month, source_url, object_key,
source_etag, file_size_bytes, sha256, schema_version, schema_hash, drift_report,
row_count_file, row_count_bronze, status, forced, error_message, started_at, finished_at`.
Status is one of `pending`, `landed`, `loaded`, `failed`, `skipped_unchanged`.
The row is also written as JSON under `manifests/` in the landing zone.

### Roles (least privilege, Q11): `infra/postgres/init/02_roles.sql`

| Role | Rights |
|---|---|
| `loader` | writes `bronze` and `ops` |
| `transformer` | reads `bronze` and `ops`, writes `silver` and `gold` |
| `publisher` | reads `gold` and `ops`, owns the `analytics` views, writes `semantic` |
| `superset_reader` | `SELECT` on `analytics` only |
| `ai_reader` | `SELECT` on `analytics` and `semantic` only; `statement_timeout = 10s`; read-only transactions. The only role that runs LLM-planned queries. |
| `ai_audit_writer` | `INSERT` on `ops.ai_audit_log` only, on a separate connection |

Verified: `loader` cannot create tables in silver or gold; `transformer` cannot modify
bronze or create in analytics; `superset_reader` and `ai_reader` cannot read bronze or ops;
a 12-second query by `ai_reader` is cancelled; warehouse roles cannot connect to
`airflow_meta`.

---

## 8. dbt: transformation, quality, star schema (planned)

Project `dbt/` (dbt-core, dbt-postgres; packages `dbt_utils`, `dbt_expectations`).

**Pinned versions** (dependency resolution trial of 16 November 2026, Python 3.12). dbt and
Airflow are installed in two separate environments, as Cosmos recommends.

| Environment | Package | Version |
|---|---|---|
| dbt | dbt-core | 1.12.7 |
| dbt | dbt-postgres | 1.11.0 |
| dbt | dbt-metricflow | 0.15.0 |
| dbt | metricflow | 0.213.0 |
| Airflow | apache-airflow | 3.4.0 |
| Airflow | astronomer-cosmos | 1.16.0 |
| Airflow | apache-airflow-providers-postgres | 7.1.2 |

The trial proves that each set of packages installs together. Running them (`dbt build`,
`mf query`, a Cosmos DAG) is verified in waves 2 and 3.

### Layers

- `models/staging/`: `stg_yellow_trips`, `stg_taxi_zones`, `stg_holidays`. Snake case names, explicit casts (timestamps, `numeric(10,2)` for amounts, `smallint` for codes).
- `models/intermediate/` (= **silver**): `int_trips_flagged` (flags, status, deduplication), `int_trips_quarantine`.
- `models/marts/` (= **gold**): `fct_trip`, dimensions, `agg_*`.
- `models/semantic/`: MetricFlow semantic models and metrics.

The `analytics` materialized views are created by `infra/postgres` and refreshed by the
publication task, **not** by dbt.

### Silver quality rules (Q3)

| Flag | Rule | Severity |
|---|---|---|
| `negative_amount` | any amount below 0 | invalid |
| `pickup_after_dropoff` | pickup ≥ dropoff | invalid |
| `duplicate` | see below | invalid |
| `out_of_period` | pickup more than 3 days away from the file month (other year, future date) | invalid |
| `implausible_speed` | speed above 80 mph | suspicious |
| `implausible_distance` | distance above 200 miles | suspicious |
| `unrealistic_duration` | duration below 1 minute or above 6 hours | suspicious |
| `zero_distance` | distance = 0 with an amount above 0 | suspicious |
| `null_zone` | pickup or dropoff zone NULL or in {264, 265} | suspicious |
| `unknown_payment` / `unknown_ratecode` | code present but outside the known list | suspicious |
| `amount_mismatch` | `total_amount` differs from the sum of its components (± 0.05) | suspicious |
| `cross_month` | pickup within 3 days before or after the file month | info |
| `not_reported` | payment type, rate code or passenger count NULL | info |

Status: `invalid` > `suspicious` > `valid`. A row with only `info` flags stays `valid`.
Thresholds are dbt `vars`.

**One list of flags**: the dbt seed `seeds/quality_flag_catalog.csv`
(`flag_code, description, severity, rule_summary, threshold_var, exam_requirement`) drives
the status calculation, the tests, `dim_trip_quality`, the data dictionary and the labels of
Dashboard 5. Adding a flag means one row in the seed and one expression in the model.

**Storage**: one boolean column per flag (`is_negative_amount`, …) is the source of truth
and is easy to filter in Superset; `quality_flags text[]` is derived for reading;
`quality_status` is derived from the highest severity.

**Duplicates**: natural key = hash of `vendor_id, pickup_ts, dropoff_ts, pu_zone, do_zone,
trip_distance, total_amount`. The row with the smallest `file_row_number` is kept, the
others are flagged `duplicate`.

**Policy for invalid records**: every row is **kept with its flags** in silver and gold
(traceability, Dashboard 5); approved metrics filter on `valid`. Only rows that cannot be
parsed go to quarantine (`silver.trips_quarantine` and the landing prefix `quarantine/`).
Silently excluding rows would distort the Valid-Trip Rate and hide anomalies.

**Rule for `cross_month` and `out_of_period`** (the flag only looks at the **pickup**; a
trip that starts on the 31st at 23:50 and ends on the 1st is normal in the file of its
pickup month):
- A `cross_month` trip is **counted on its real pickup date**.
- Deduplication also compares the neighbouring month. The row whose `source_month` equals its pickup month wins; the late copy is flagged `duplicate`. On each load of month M, the `cross_month` rows of M-1 and M+1 are re-evaluated.
- Loading file M can add trips dated in M-1, so `agg_*` tables are recomputed for pickup months M-1 to M+1.
- The bronze → silver reconciliation is by `source_month` (file); metrics are by pickup date.

**Measured on the loaded months** (details in `docs/evidence/q03/first_month_measures.md`):

| File | Pickup in month | Within 3 days | Far from the month |
|---|---|---|---|
| 2024-12 | 3,668,337 | 26 | 8 (from year 2008 to March 2025) |
| 2025-01 | 3,475,204 | 22 | 0 |

The 3-day tolerance separates the two groups with no ambiguous row.

**NULL is not an unknown code.** In 2025-01, 540,149 rows (15.54 %) have
`payment_type = 0`, and **all** of them have a NULL rate code and passenger count; they
carry about 10.8 M USD of 89 M USD of `total_amount`. In 2024-12 they are 326,291 rows
(8.9 %). They stay `valid` with the `not_reported` flag: marking them `suspicious` would
remove 15 % of trips and 12 % of revenue from approved metrics without a business reason.
Tip metrics stay limited to `payment_type = 1`; breakdowns by rate code or passengers show
a "Not reported" category. `ratecodeid = 99` (41,963 rows) is a present code and is flagged
`unknown_ratecode`.

**Bronze → silver reconciliation**: `gold.recon_bronze_silver` (per month: bronze rows,
silver rows, rows per status, sum of `total_amount` in bronze versus valid silver, gap
explained per flag) with a test that fails when a gap is not explained.

### Star schema (Q4), grain: one completed taxi trip

- `fct_trip`: `trip_sk` = `generate_surrogate_key(source_month, file_row_number)`, `source_month`, `file_row_number`, `batch_id`, foreign keys (`date_sk, pickup_time_sk, pickup_zone_sk, dropoff_zone_sk, payment_type_sk, rate_code_sk, vendor_sk, service_period_sk, trip_quality_sk`), measures (fare, extra, mta_tax, tip, tolls, improvement_surcharge, congestion_surcharge, airport_fee, cbd_congestion_fee, total_amount, distance, duration_min, speed_mph, passenger_count), `is_airport_trip`, `quality_status`, `quality_flags`. Incremental `delete+insert` by `source_month`; indexes on `(date_sk)` and `(pickup_zone_sk)`, BRIN on `pickup_ts`.
- Required dimensions: `dim_date` (`is_holiday`, `holiday_name`, `is_weekend`), `dim_time`, `dim_pickup_zone` and `dim_dropoff_zone` (role-playing views of `dim_zone`: borough, zone, service_zone, `is_airport`, `is_manhattan_core`), `dim_payment_type`, `dim_rate_code`.
- Extensions: `dim_vendor`, `dim_service_period` (AM peak 7–10, PM peak 16–20, late night 0–5, off-peak), `dim_trip_quality` (junk dimension of flag combinations).
- **"Unknown" member** (key `-1`) in every dimension: NULL zones, unknown codes, dates out of range.
- **Full refresh** when a quality rule, a dimension or the source contract changes.

### Aggregates (sums and counts only), published in `analytics`

| Table | Grain | Used by |
|---|---|---|
| `agg_trips_daily` | day × pickup zone × payment type × rate code × vendor × status | Dashboards 1, 4, 5 |
| `agg_trips_hourly` | day × hour × pickup zone × airport flag | Dashboards 2, 6; `trips_per_active_hour` |
| `agg_routes_monthly` | month × pickup zone × dropoff zone × service period | Dashboards 3, 6 |
| `agg_quality_daily` | day × vendor × borough × flag | Dashboard 5 |
| `agg_route_duration_baseline` | route × hour: reference median and MAD versus current month (robust z-score) | Dashboard 5 |
| `ops_freshness`, `ops_batches` | per month / per batch | "last refreshed" tile, Dashboards 1 and 5 |

Every materialized view has a unique index (required by `REFRESH ... CONCURRENTLY`).

### dbt tests

`unique` and `not_null` on every key, `accepted_values` on codes, `relationships` from the
fact to the dimensions, at least one business assertion (`total_amount` ≈ sum of components
± 0.05 for valid rows), source `freshness` (warn 45 days, error 75 days on `ingested_at`),
enforced contracts on marts, dbt unit tests on the flag logic, volume test against the
previous month. **Blocking tests are on silver.**

### Macros (Q4.5)

`quality_flag_array()`, `safe_divide()`, `month_partition_replace()` (pre-hook), `unknown_member()`.

### Exposures and documentation

`models/exposures.yml` declares the six Superset dashboards and the AI assistant as dbt
`exposures`, so the lineage graph goes from the source file to the dashboard (Q11).
`dbt docs generate` is served in Compose (port 8085) and exported to `docs/dbt_docs/`.

---

## 9. Semantic layer and governed metrics (planned, Q6)

Metrics are defined in `dbt/models/semantic/*.yml` (MetricFlow), the **single source of
truth**. Each metric carries in `meta:` its `owner`, `sql_expression` (an aggregate
expression on an `analytics` table), `base_table`, `grains`, `dimensions`, `filters` and
`is_estimate`. Default owner: `AYEBIE GRAM MESCHAC (Data Team)`. Grains: day, week, month (and hour for
demand).

| # | Metric | Formula (at read time, on aggregates) | Filters and rules |
|---|---|---|---|
| 1 | `trips` | `sum(trip_count)` | valid |
| 2 | `total_revenue` | `sum(sum_total_amount)` | valid; **includes** tolls, surcharges, congestion fees, airport fee and recorded tips |
| 3 | `avg_fare` | `sum(sum_fare) / sum(trip_count)` | valid |
| 4 | `avg_tip` | `sum(sum_tip) / sum(trip_count)` | valid **and card** (cash tips are not recorded) |
| 5 | `tip_rate` | `sum(sum_tip) / sum(sum_fare)` | valid, card only |
| 6 | `avg_distance` | `sum(sum_distance) / sum(trip_count)`, miles | valid |
| 7 | `avg_duration` | `sum(sum_duration_min) / sum(trip_count)` | valid |
| 8 | `revenue_per_mile` | `sum(sum_total_amount) / sum(sum_distance)` | valid, distance > 0 |
| 9 | `trips_per_active_hour` | `sum(trip_count) / count(distinct date_hour)` on `agg_trips_hourly` | valid |
| 10 | `airport_trips` | `sum(trip_count)` where `is_airport_trip` (pickup or dropoff in {1 EWR, 132 JFK, 138 LGA} or rate code in {2, 3}) | valid |
| 11 | `congestion_fee_revenue` | `sum(sum_cbd_congestion_fee)` | valid; distinct from `congestion_surcharge` |
| 12 | `valid_trip_rate` | `sum(trip_count) filter (valid) / sum(trip_count)` | **all** rows |
| + | `airport_fee_revenue`, `congestion_surcharge_revenue`, `est_co2_kg` (`sum(distance) × factor`) | | `est_co2_kg` is a labelled **estimate**; factor and limits documented |

**metrics-sync** (`services/metrics_sync/`) reads the YAML and (1) creates or updates the
certified Superset datasets through the REST API (metrics, descriptions, owners),
(2) generates `semantic.metric_catalog` for the AI assistant. It does not translate
anything: it copies `sql_expression`.

**Consistency test (Q6.4)**: `tests/consistency/test_metric_parity.py` computes
`total_revenue` and `trips` for one month through (i) `mf query` on `fct_trip`, (ii) the
Superset chart data API, (iii) the FastAPI endpoint. The three values must be identical;
the result is exported to `docs/evidence/q6/reconciliation.md`.

**Stated limitation**: open-source MetricFlow is not queried directly by Superset. The
governed fallback is `sql_expression` with certified datasets, controlled by the
consistency test.

---

## 10. Superset and the six dashboards (planned, Q7 and Q13)

Superset with Redis (cache), connected with `superset_reader` to the `analytics` schema
only. **Certified** datasets, row-level security by role (for example `analyst_manhattan`
only sees Manhattan). Global date filters, cross-filters, a "last refreshed" tile, and a
drill-down path Executive → zone → hour → payment type → route.

Every dashboard has a **data-quality tile** (`valid_trip_rate` of the filtered period and
its status against the agreed threshold) and ends with a Markdown block: a plain-English
"so what?" insight and a recommended next question.

| # | Dashboard | Strategic question | Key elements |
|---|---|---|---|
| 1 | Executive Pulse | Are trips and revenue healthy? | week-over-week and month-over-month KPIs, revenue decomposition (volume, distance, fare, tolls, fees), valid versus all rows, borough contribution, freshness and completeness |
| 2 | Demand Rhythm | When should capacity increase? | hour × weekday heatmap, weekday / weekend / holiday, trips per active hour by borough, peaks, seasonality versus a 3-month baseline, airport versus city |
| 3 | Geography and Routes | Where is the value moving? | choropleth map, top zones, growing and declining dropoff zones, pickup → dropoff routes, volume versus revenue per mile, airports |
| 4 | Fare, Payment and Customer | What is changing in trip economics? | fare components over time, tip rate by payment type / borough / hour / fare band, cash and card shares, rate codes, fare per mile, `cbd_congestion_fee` |
| 5 | Service Efficiency and Anomalies | Where should leaders look closer? | long durations, suspicious rate by vendor / borough / month, normal versus current duration (z-score), row counts per batch, quality threshold "pause decision" |
| 6 | City and Airport Strategy | What action should we take next? | airport demand, mix of airport / Manhattan core / outer boroughs, demand versus revenue, underserved zones (proxy), **estimated CO₂**, top three actions with validating analysis |

Year-over-year comparison is not available with 13 months (only December 2024 versus
December 2025): month-over-month is used and the limit is stated.

Exports: `superset/dashboards/*.zip`, screenshots in `docs/evidence/q7/`, note `docs/dashboards.md`.

---

## 11. AI assistant (planned, Q8, Q9, Q10)

Stack: FastAPI (`app/api/`), React (`app/web/`), Ollama (`qwen2.5:14b` as the main model,
`qwen2.5:3b` for comparison and demonstration mode), Pydantic v2, SQLGlot.

### Flow

```
Manager question
 → compact catalogue in the prompt (metrics, dimensions, templates, examples)
 → Ollama with structured output (JSON Schema) → QueryPlan / ReportRequest (Pydantic)
 → schema and policy validation (allow-listed metrics and dimensions, dates in coverage, consistent filters)
 → pre-approved parameterised SQL template on analytics (never SQL written by the model)
 → SQLGlot: SELECT only, allow-listed tables, LIMIT
 → PostgreSQL through ai_reader (read-only, 10 s timeout, at most 5,000 rows)
 → deterministic result + provenance (metric, formula, source period, refresh time, filters, rendered SQL)
 → Ollama: narrative from the AGGREGATES ONLY + suggested chart + follow-up question
```

The LLM plans and explains; it never calculates. Each step writes a row to
`ops.ai_audit_log` (session, question, plan, validation verdict, template, rendered SQL,
duration, prompt variant, error).

### Pydantic schemas

- `QueryPlan`: `intent (trend|compare|rank|breakdown|lookup|clarify|unsupported)`, `metrics` (enum generated from the catalogue), `dimensions`, `filters`, `date_range`, `comparison_period`, `grain`, `limit`.
- `ReportRequest` (Q8): adds `chart_recommendation`, `dashboard_title`, `explanation`.
- `Answer`: `data_summary`, `narrative`, `provenance`, `active_filters`, `limitations`, `suggested_followup`.

### API (tested before any screen is built)

`POST /sessions` · `POST /sessions/{id}/ask` · `POST /sessions/{id}/reset` · `GET /catalog` ·
`POST /reports` (creates a draft) · `GET /reports/{id}` (specification, preview, summary) ·
`POST /reports/{id}/confirm` (publishes) · `GET /health`.

### Requirements

- Multi-turn session with visible active filters and a reset / "new analysis" action.
- Vague question → clarification; empty result; out-of-scope question (driver earnings, wait time → explained refusal); Ollama down → degraded message and HTTP 503; query failure.
- **Visible quality**: the `provenance` of every answer includes the `valid_trip_rate` of the queried period and a warning when it is below the threshold.
- **Least privilege on Superset**: the API uses a dedicated Superset service account (`ai_builder`) that can only create and modify its own drafts on certified datasets. The API itself is protected by a token (`API_TOKEN` in `.env`).
- **Superset builder (Q8)**: draft chart or dashboard through the REST API (prefix `[DRAFT]`, chart types limited to fixed templates), **published only after explicit confirmation**.
- **Three prompt variants** (planning and narration) versioned in `app/api/prompts/`, compared on the evaluation pack (correctness, clarity, hallucination risk) → `docs/evidence/q9/prompt_variants.md`.

### React front end: `app/web/`

Vite, TypeScript, Tailwind, TanStack Query, Recharts. Types are generated from the FastAPI
OpenAPI schema (`openapi-typescript`, `make types`); no API type is written by hand. Served
as static files (nginx) in Compose. Screens: conversation (visible active filters, reset
button, collapsible structured plan and provenance, Recharts chart of the result) and
report builder (specification, preview, summary, confirmation button).

**Plan B**: if the front end is not ready **at the end of day 12 (27 November)**,
`app/streamlit/` is built on the same API and the React front end is dropped, not continued
in parallel.

### Evaluation pack (Q10): `evals/cases.yaml`, at least 15 cases

Normal ×3, multi-turn follow-up ×2, ambiguous ×2, unsupported ×2, empty result, malicious
instruction, invalid date, conflicting filters, model unavailable, dashboard creation.
Fields: `expected_intent, expected_metrics, expected_filters, expected_behaviour, outcome`.
Runner: `make eval` → `docs/evidence/q10/eval_results.md`. One observed failure and its
specific fix are documented.

---

## 12. Extensions (planned, only when the core is green, in this order)

1. **Prometheus + Grafana** (profile `obs`): Airflow (StatsD), postgres_exporter, FastAPI; alerts on failed run, freshness and rejection rate.
2. **Kafka KRaft + Schema Registry** (profile `stream`): `trips.raw` replays a Parquet file to simulate the current month; the consumer writes `bronze.yellow_trips_stream` (`is_provisional = true`), **excluded from `fct_trip` and from metrics**, purged when the official file arrives.
3. **MLflow + demand forecast** by zone × hour (profile `ml`): LightGBM (calendar, holidays, lags) against a naive seasonal baseline; forecasts → `ml.demand_forecast` → Dashboard 2.

---

## 13. Orchestration and Docker Compose

**Airflow (planned)**: DAG `monthly_yellow_pipeline`, monthly, targets M-2, retries with
backoff, `max_active_runs=1` (no overlapping runs), `catchup=False` with manual backfill
through a `month` parameter, deadline alerts, safe re-run with
`dag_run.conf={"month": "2025-03", "force": true}`.

**After a partial failure**: every task can be replayed; landing and bronze are idempotent;
`analytics` is never refreshed until the build is green.

**Operational signals (Q5.4)** in `ops.pipeline_signals`: freshness, volume versus the
previous month, rate of invalid and suspicious rows, dbt test pass rate, task duration.

**CI (planned)**: ruff, sqlfluff, pytest, eslint and tsc.

### Services

| Service | Port | Profile | Status |
|---|---|---|---|
| postgres 16 | 5432 | core | built |
| rustfs (S3 API / console) | 9000 / 9001 | core | built |
| ingestion (one-shot job) | – | tools | built |
| airflow (api-server, scheduler, dag-processor, triggerer) | 8080 | core | planned |
| dbt-docs | 8085 | core | planned |
| superset + redis | 8088 | bi | planned |
| ollama | 11434 | ai | planned |
| api (FastAPI) | 8000 | ai | planned |
| web (React, nginx) | 3000 | ai | planned |

Health checks on every service, named persistent volumes,
`depends_on: condition: service_healthy`.

---

## 14. Build plan (16 → 30 November)

| Wave | Days | Content | Acceptance criteria |
|---|---|---|---|
| **1** | D1–D2 (16–17) | Repository, Compose `core`, schemas and roles, RustFS, idempotent ingestion and manifest, partitioned bronze, zones; **compatibility trial** Airflow 3 / Cosmos / dbt / MetricFlow with pinned versions | ingestion of 2025-01 succeeds; re-run = `skipped_unchanged`; missing month = logged failure; file count = bronze count; 2024-12 loaded with contract v2024 |
| **2** | D3–D5 (18–20) | dbt staging / silver / gold, flags, deduplication, star schema, aggregates, tests, contracts, macros, docs, reconciliation | `dbt build` green on all months; reconciliation explained; identical `trip_sk` after a re-run; one deliberately broken test can be shown |
| **3** | D6–D7 (21–22) | Airflow + Cosmos, full DAG, `analytics` publication, signals, notifications | successful run, forced re-run, and failing test ⇒ `analytics` unchanged, all logged |
| **4** | D8–D10 (23–25) | MetricFlow, metrics-sync, Superset (certified datasets, RLS, six dashboards with insights) | `total_revenue` identical in MetricFlow and Superset; six dashboards exported |
| **5a** | D11 (26) | Complete FastAPI: planner, validator, resolver, Superset builder, audit log, tests | API tests green; 3-surface consistency; one rejected request logged; draft created then confirmed through the API |
| **5b** | D12 (27) | React front end on the API | multi-turn conversation and builder usable; **otherwise switch to Streamlit** |
| **5c** | D13 (28) | Evaluation pack, three prompt variants, end-to-end smoke test | `make eval`; multi-turn transcript; `make smoke` |
| **6** | D14 (29) | Extensions of section 12, in order | each one demonstrable or not started |
| **Final** | D15 (30) | Final README, proposal, governance note, diagrams, demonstration video, zip | submission checklist complete |

If time runs short, extensions are dropped first (MLflow → Kafka → Grafana). Q3, Q4, Q8 and
Q9 are never cut.

---

## 15. Repository layout

```
├── README.md
├── Makefile
├── docker-compose.yml
├── .env.example
├── infra/postgres/init/     # schemas, roles, bronze and manifest tables
├── ingestion/               # landing, source contracts, manifest, bronze loader, tests
├── docs/
│   ├── exam/                # exam paper
│   └── evidence/            # logs, measures and screenshots per question
│
│   Added by later waves:
├── airflow/dags/            # monthly_yellow_pipeline.py
├── dbt/                     # models/{staging,intermediate,marts,semantic}, macros, tests, seeds
├── services/metrics_sync/
├── app/api/                 # FastAPI: planner, validator, resolver, superset_client, narrator, prompts/
├── app/web/                 # React (Vite)
├── superset/dashboards/     # exports
├── evals/                   # cases.yaml, runner
├── tests/                   # consistency, end-to-end smoke
└── data/sample/             # permitted sample (one day)
```

**Submission checklist**: Git repository and zip · source code · dbt project · DAGs · Docker
files · `.env.example` · tests · architecture and data-model diagrams · data dictionary ·
metric catalogue · dashboard exports or screenshots · evaluation pack · README · video.

**Defence checklist**: trigger an Airflow run and trace one trip (row N of the Parquet file
→ `fct_trip`) · show dbt lineage and a failing test, and prove `analytics` did not move ·
explain one metric identically in dbt, Superset and the assistant · ask a natural-language
question and show the structured plan, governed query and provenance · request a draft
dashboard and explain the approval step · show a limitation the platform honestly refuses
(for example driver earnings).

---

## 16. Engineering rules

1. **Build in waves.** Each wave leaves a platform that runs end to end. A wave does not start until the previous one meets its acceptance criteria.
2. **Every component is justified in one sentence.** If an addition does not improve a mark or the defence, it is not added. The core comes before any extension.
3. **Full traceability**: any displayed number can be traced from the row of the raw file to bronze, silver, gold, the metric and the chart or AI answer.
4. **The LLM plans and explains, it never calculates.** No SQL produced by the LLM is executed.
5. **Idempotence everywhere**: re-running a month replaces the month partition, with no duplicates and the same keys.
6. **Secrets only in `.env`** (never committed). `.env.example` is updated with every new variable.
7. **Evidence** (logs, screenshots, test outputs) is saved in `docs/evidence/qXX/` as work progresses.
8. Code and documentation are in English.
9. Quality: `ruff` and `ruff format` (Python), `sqlfluff` (postgres dialect, dbt templater), type hints, `pytest`; `eslint` and `tsc --noEmit` (front end).
10. A task is finished only when its tests have been run and their output shown.
11. **The API comes before the front end**: no screen is started until its endpoint is tested.

---

## 17. Known limitations

- Data is reported by vendors; TLC does not guarantee its accuracy.
- The platform does not measure driver earnings, rider identity, wait time, cancellations, real emissions or profitability.
- Cash tips are not recorded: tip rate applies to card trips only.
- About 9 to 16 % of rows per month have no payment type, rate code or passenger count reported.
- Trip volume is a **proxy** for demand: unserved demand is invisible.
- CO₂ is an estimate based on a distance factor.
- Geographic bias: Yellow Taxi coverage is centred on Manhattan and the airports.
- Correlation is not causation.
- No full year-over-year comparison with 13 months.
- MetricFlow is not connected directly to Superset (governed fallback and consistency test).
- The LLM can misinterpret a question: validation, provenance and human review are required.

Future improvements: a columnar warehouse engine for larger volumes, a semantic layer
queried directly by every tool, separate environments and backups.

---

## 18. Next step

Wave 2: the dbt project (staging, silver with quality flags, star schema, aggregates, tests
and reconciliation).
