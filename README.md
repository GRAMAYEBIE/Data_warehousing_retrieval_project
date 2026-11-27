# NYC Taxi Insight Hub

End-to-end data warehouse, BI and AI analytics platform on NYC TLC Yellow Taxi trip records.
Final project for **DS6102 Data Warehousing and Information Retrieval** (Academic City University, lecturer: Jeremiah Ishaya).

- Author: AYEBIE GRAM MESCHAC
- Project window: 16 to 30 November 2026 (15 days)
- Full exam paper: `docs/exam/DS6102_sujet.pdf`

  
This document is the project reference: what is built, how to run it, the design decisions
and the results measured on the real data. The project report (`docs/report.pdf`) answers
the exam questions one by one and points back here for the details.

---

## 1. Status

| Wave | Scope | Status |
|---|---|---|
| 1 | Docker Compose core, warehouse schemas and roles, landing zone, idempotent ingestion, bronze layer, manifest | **Built and verified** |
| 2 | dbt: silver, quality flags, star schema, aggregates, tests, reconciliation | **Built and verified** (94/94 build steps green on two months) |
| 3 | Airflow orchestration, publication gate, operational signals | **Built and verified** (successful run, failure and recovery, safe re-run) |
| 4 | Semantic layer, Superset, six dashboards | **Built and verified**: semantic layer, metric parity 40/40 on three surfaces (MetricFlow, published SQL, Superset), 10 certified datasets, 6 dashboards (57 charts, each verified to return data) |
| 5 | AI assistant: API, web interface, evaluation pack | **Built and verified**: governed planner, validator, approved templates, number checks (86 API tests); conversational answers streamed from a local model (`qwen2.5:7b`); React interface (Overview, Forecast, Shift planner, Ask, Report builder), voice input; evaluation pack |
| 6 | Observability: metrics, logs, traces, alerts (Prometheus, Loki, Tempo, Grafana) | **Built and verified**: 12 services, 6 dashboards and 14 alert rules as code; a question gives a trace and a log line with the same trace id |
| 7 | MLflow and demand forecasting (needs six months) | **Built and verified**: trips and revenue per zone and hour; a seasonal baseline, an adjusted baseline and LightGBM compete on rolling backtests; every month is checked against what happened, drift is flagged and the next training reacts to it ([section 12](#demand-forecast-wave-7-profile-ml)) |
| 8 | Kafka: provisional stream of the current month | **Built and verified**: June 2025 replayed through Kafka (4,322,960 trips, 74 rejected by the contract), watched live against its forecast ([section 12](#streaming-wave-8-profile-stream)) |

Loaded and published: **22 months, `2024-12` to `2026-09`** (the latest TLC file in
November 2026), one Airflow run each, in order, plus the 265 taxi zones. The platform was
built on the first six months; June 2025 was streamed through Kafka before its official
load; each later month checked the forecast made for it. Documents: `docs/proposal.pdf`
(Q1), `docs/report.pdf` (project report), `docs/data_dictionary.md`, `docs/diagrams/`.

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

Requirements: Docker with Docker Compose, and Python 3 (standard library only) for the
bootstrap. Tested with Docker 29 and Compose v5 on Windows 11 and on macOS 15 (Apple M4);
see [Windows and macOS](#windows-and-macos) for the differences.

### One command, from a fresh clone

```bash
git clone <this repository> && cd <repository>
python scripts/bootstrap.py all --months 2024-12..2025-05
# GPU machine (NVIDIA Container Toolkit): a larger model on the GPU
python scripts/bootstrap.py all --months 2024-12..2025-05 --gpu --model qwen2.5:7b --max-active-tasks 3
```

`scripts/bootstrap.py` creates `.env` with random secrets (never overwrites an existing
one), starts the core services, loads the taxi zones, runs the Airflow pipeline once per
month in order (each run waited for, months already loaded are skipped), builds Superset
and the six dashboards, then downloads and loads the model and checks the assistant's
health. Each step runs alone (`env`, `core`, `load`, `bi`, `ai`) and can be run again.
`--low-memory` stops Superset and Airflow before the assistant starts (8 GB laptop).

### Windows and macOS

| | Windows 11 | macOS (Apple Silicon) |
|---|---|---|
| Docker | Docker Desktop with the WSL 2 backend | Docker Desktop |
| Memory for Docker | 4 GB on an 8 GB laptop, with WSL swap (see [Local resources](#local-resources)) | 10 GB on a 16 GB machine (Settings → Resources) |
| Python command | `python scripts/bootstrap.py ...` | `python3 scripts/bootstrap.py ...` |
| GPU for the model | `--gpu` with an NVIDIA GPU and the NVIDIA Container Toolkit | Docker on macOS cannot use the Apple GPU: run Ollama on the host (below) |
| Shell for the `make` targets | Git Bash or WSL | Terminal (zsh) |

The images are multi-architecture or built locally, so the same commands run on `x86_64`
and on `arm64`. Measured on one month each (2025-04, 4.0 million trips, on the laptop;
2024-12, 3.7 million trips, on the Mac from a fresh clone):

| Step | Windows laptop (4 CPUs, 4 GB for Docker) | Mac mini M4 (10 CPUs, 10 GB for Docker) |
|---|---|---|
| Bronze load | 6 min | 0.3 min |
| Silver quality flags (`int_trips_flagged`) | 53 min | 0.8 min |

**The model on the Apple GPU (macOS).** Ollama runs on the host, the API reaches it through
`host.docker.internal`; it listens on the Mac only (127.0.0.1), nothing is opened on the
network. Measured on the 17 data cases of the evaluation pack (all passed in each run):

| Model | Ollama in Docker (CPU) | Ollama on the host (Metal GPU) |
|---|---|---|
| qwen2.5:3b | 8.8 s median | 3.7 s median |
| qwen2.5:7b | 19.6 s median | 8.3 s median |

```bash
# Official macOS build of the same Ollama version, in the user's home (no administrator)
curl -fsSLO https://github.com/ollama/ollama/releases/download/v0.40.12/ollama-darwin.tgz
mkdir -p ~/ollama-native && tar -xzf ollama-darwin.tgz -C ~/ollama-native
OLLAMA_HOST=127.0.0.1:11435 ~/ollama-native/ollama serve &      # or a launchd agent
OLLAMA_HOST=127.0.0.1:11435 ~/ollama-native/ollama pull qwen2.5:7b
# .env
OLLAMA_URL=http://host.docker.internal:11435
OLLAMA_MODEL=qwen2.5:7b
```

During a long load on macOS, keep the machine awake (`caffeinate -ims` in a terminal, or
System Settings → Energy → "Prevent automatic sleeping when the display is off"). On
Windows, keep the laptop plugged in and out of sleep.

**Continuous integration** (`.github/workflows/ci.yml`, every push): lint, formatting and
unit tests of the five Python components (ingestion, assistant API, metrics sync and
dashboards, Airflow operations, bootstrap), `dbt parse` with a check that the semantic
manifest holds the governed metrics, and `docker compose config` on every profile with
`.env.example`. No secret is needed.

### Step by step

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

`yellow` runs the two steps that Airflow runs separately: `land` (source → validated file
in RustFS) and `load` (RustFS → bronze, after checking the SHA-256 against the manifest).
`check` only tells whether a month is published.

Exit codes of the ingestion command: `0` success (including "unchanged, nothing to do"),
`2` source file not available, `3` file or contract rejected, `4` nothing landed to load,
`1` any other failure.

The init scripts in `infra/postgres/init/` run only when the PostgreSQL volume is created
for the first time. `04_ops_pipeline.sql` is idempotent and can be applied to an existing
warehouse with
`docker compose exec -T postgres psql -U postgres -d warehouse -f /docker-entrypoint-initdb.d/04_ops_pipeline.sql`.

### Running the whole pipeline with Airflow

```bash
# 7. Start Airflow (init job: database migration and dbt manifest; then API, scheduler,
#    DAG processor). UI: http://localhost:8080, user admin, password AIRFLOW_ADMIN_PASSWORD.
docker compose --profile core --profile orchestration up -d

# 8. Run the pipeline for one month (or use "Trigger DAG" in the UI with the same parameters)
make run-month MONTH=2025-02          # make run-month-force MONTH=2025-02 to reload
```

Once dbt files change, refresh the manifest Cosmos reads with
`docker compose --profile core --profile tools run --rm --no-deps dbt parse` (on a fresh
clone, run `dbt deps` the same way first: the packages are installed in the Airflow image,
not in the standalone dbt service). `--no-deps` matters while Airflow runs: without it,
Compose may recreate PostgreSQL to match the Compose file, which stops the running tasks.

### Evidence of the three required behaviours (Q2)

| Behaviour | Result | Log |
|---|---|---|
| Successful run | `2024-12` loaded, 3,668,371 rows in the file and in bronze | `docs/evidence/q02/run_2024-12_contract_v2024.log` |
| Safe re-run | `2025-01` → `skipped_unchanged` in 4 seconds | `docs/evidence/q02/rerun_2025-01_skipped_unchanged.log` |
| Failure mode | `2027-01` → `failed`, HTTP 403 recorded in the manifest, exit code 2 | `docs/evidence/q02/failure_2027-01_source_missing.log` |
| Forced re-run | `2025-01` reloaded with `--force` | `docs/evidence/q02/forced_rerun_2025-01.log` |

### Local resources

The development machine has 8 GB of RAM and 4 CPUs, with 4 GB given to Docker. One month
takes about 1.2 GB in bronze and 5 to 10 minutes to load. Two months take 2.4 GB in bronze,
3.2 GB in silver and 2.5 GB in gold; thirteen months are projected at about 15 GB in
bronze and 40 to 45 GB with silver and gold.

| Profile | Memory used (measured) | Notes |
|---|---|---|
| `core` (PostgreSQL, RustFS) | about 0.8 to 1.1 GB | enough for ingestion and dbt alone |
| `core` + `orchestration` (Airflow) | about 1.7 to 2 GB at rest | dbt builds add PostgreSQL work memory on top |

**On an 8 GB Windows laptop, configure WSL swap.** Without it, the Docker VM had 1 GB of
swap and PostgreSQL lost a process during a dbt build while Airflow was running (see
`docs/evidence/q05/README.md`). `infra/wsl/wslconfig.example` keeps 4 GB of RAM for Docker
and adds 12 GB of swap on a data drive; copy it to `%USERPROFILE%\.wslconfig`, run
`wsl --shutdown` and restart Docker Desktop. It also gives the VM **3 of the 4 CPUs**: with
all 4, the kernel log showed "soft lockup" warnings (a CPU starved for more than 20 s) and
PostgreSQL backends were killed; leaving one CPU to Windows stopped it. PostgreSQL runs
without parallel workers or JIT, and the pipeline runs one task at a time
(`PIPELINE_MAX_ACTIVE_TASKS=1`). On a larger machine, raise all of them.
For a quick demonstration on a small machine, load a single month (`make ingest
MONTH=2025-01`, then `make run-month MONTH=2025-01`) and use the smaller model
`qwen2.5:3b`; six months are needed for the forecast.

---

## 4. Architecture

```
SOURCES                    LANDING (RustFS S3)            ORCHESTRATION
TLC Yellow Parquet   ──►   raw/yellow/year=/month=/  ◄──  Airflow 3 + Cosmos
 (2024-12 → 2026-09)       manifests/                     monthly DAG, targets M-2
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
  analytics published copy of the approved gold tables + BI materialized views on that copy
  semantic  metric_catalog (generated from the dbt metric YAML)
  ops       ingestion_manifest, pipeline_runs, pipeline_signals, ai_audit_log
─────────────────────────────────────────────────────────────────────────
        │ superset_reader                    │ ai_reader (read-only, 10 s)
        ▼                                    ▼
  Superset + Redis                    FastAPI ──► Ollama (qwen2.5:7b)
  6 certified dashboards                 │  └──► Superset REST API (drafts)
                                         ▼
                                  React UI (Vite)

  Extensions: ml (MLflow, forecasts, forecast against actual) · stream (Kafka, provisional
  trips of the current month) · observability (Prometheus, Grafana, Loki, Tempo)
```

The same architecture is drawn in `docs/diagrams/architecture.svg`, and the star schema in
`docs/diagrams/star_schema.svg`.

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
5. **Publish**: the approved gold tables are copied to `analytics` and swapped, and the BI materialized views are rebuilt on the copy, in **one transaction**, **only if step 4 is green**. Otherwise users keep the previous state and an alert is sent.
6. **Refresh Superset**: metric YAML → `semantic.metric_catalog` and certified Superset datasets (which invalidates the chart cache), then the six dashboards are rebuilt from the new publication.
7. **Operational signals** written to `ops.pipeline_signals`; notification (log + webhook).

Every step runs in the Airflow DAG.

---

## 5. Architecture decisions

| Decision | Justification |
|---|---|
| **Publication gate** | Superset and the AI assistant read **only** `analytics` (a copy of the approved gold tables), replaced by a separate Airflow task when the whole `dbt build` is green. dbt tests a table *after* writing it: without this gate, a failed test would leave wrong numbers visible. |
| **Deterministic technical identifier** | `(source_month, file_row_number)` instead of a database sequence: keys are identical after a reload, and a trip can be traced back to its exact row in the raw file. |
| **Additive aggregates only** | Aggregate tables store sums and counts; averages and ratios are computed at read time. An average of averages is wrong. |
| **Each metric formula is written once** | In the `meta:` block of the dbt YAML. Superset and the AI assistant copy it through `metrics-sync`. This makes the Q6 consistency check verifiable. |
| **The AI only uses templates on `analytics`** | `ai_reader` has no right on gold. MetricFlow (which reads `fct_trip`) is the "dbt" surface of the consistency check, not the engine of the assistant. |
| **RustFS instead of MinIO** | The exam allows an equivalent S3-compatible store with a written justification. The MinIO community edition stopped publishing binaries and container images in October 2025, went into maintenance mode in December 2025, and its repository was archived (read-only) on 25 April 2026 (github.com/minio/minio; itsfoss.com/news/minio-moves-away-from-open-source). A platform meant to be run again needs a maintained image. Image pinned to `rustfs/rustfs:1.0.6`. |
| **React (Vite) front end, not Next.js** | Vite + TypeScript + Tailwind + TanStack Query + Recharts. Types generated from the FastAPI OpenAPI schema. |
| **No DuckDB** | PostgreSQL is the required warehouse; a second engine would be a competing source of truth. |
| **Metric catalogue in the prompt, targeted retrieval** | About 15 metrics fit in the prompt; the exam asks for a "compact semantic catalogue". Retrieval adds only what a small model needs per question: the vocabulary values the question names ("Manhatan" → Manhattan) and the two or three closest validated example plans. Numbers never come from retrieved text. |
| **AI audit log in PostgreSQL** | `ops.ai_audit_log` and prompts versioned in git replace Langfuse (which needs ClickHouse, Redis and S3). It provides the guardrail logs required by Q9. |
| **Kafka kept as an extension** | Not required; it shows the streaming vision. Provisional rows **never** enter `fct_trip` or governed metrics. |
| **Left out** | pgvector, Langfuse, PgBouncer, pgAdmin, Celery beat, NOAA weather, OpenMetadata, Traefik: each would add a service without improving a mark or the defence. (Loki, Tempo and OpenTelemetry, first left out, were added with the observability wave.) |

---

## 6. Source contract

| Source | URL | Notes |
|---|---|---|
| Yellow Taxi Parquet | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{YYYY}-{MM}.parquet` | One file per month. **22 months loaded: 2024-12 → 2026-09**, the latest file published in November 2026; later months load on the monthly schedule. |
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

Licence and use: public data published by the NYC Taxi and Limousine Commission
(https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) under the NYC Open Data
terms of use; field definitions in the TLC Yellow Taxi data dictionary
(https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf).
The project's own data dictionary is `docs/data_dictionary.md`.

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
| `superset_reader` | `SELECT` on `analytics` only (and on the forecasts in `ml`, the provisional trips in `stream`) |
| `ai_reader` | `SELECT` on `analytics` and `semantic` only (plus `ml` and `stream` for the forecast pages); `statement_timeout = 10s`; read-only transactions. The only role that runs LLM-planned queries. |
| `ai_audit_writer` | `INSERT` on `ops.ai_audit_log` only, on a separate connection |
| `forecaster` | reads `analytics`, writes the `ml` schema only (`08_ml.sql`) |
| `streamer` | `SELECT` and `INSERT` on `stream.yellow_trips` and its rejects only (`09_stream.sql`) |

Verified: `loader` cannot create tables in silver or gold; `transformer` cannot modify
bronze or create in analytics; `superset_reader` and `ai_reader` cannot read bronze or ops;
a 12-second query by `ai_reader` is cancelled; warehouse roles cannot connect to
`airflow_meta`.

---

## 8. dbt: transformation, quality, star schema

Project `dbt/` (dbt-core, dbt-postgres; package `dbt_utils`). Staging, silver, quality
flags, star schema, aggregates and the reconciliation are built and tested.

```bash
docker compose --profile core --profile tools run --rm dbt deps     # once
docker compose --profile core --profile tools run --rm dbt build    # new or changed months only
docker compose --profile core --profile tools run --rm dbt build --vars "{months: ['2025-01-01']}"  # one month
docker compose --profile core --profile tools run --rm dbt docs generate
```

### Results on the two loaded months (17 November 2026)

`dbt build`: **94 of 94 steps passed** (22 models and seed, 72 tests), 44 minutes on the
development machine. Log: `docs/evidence/q04/dbt_build_two_months.log`.

| Source file | Bronze rows | Silver rows | Quarantine | Unexplained | Valid | Suspicious | Invalid | Valid-trip rate |
|---|---|---|---|---|---|---|---|---|
| 2024-12 | 3,668,371 | 3,668,371 | 0 | 0 | 3,435,481 | 153,480 | 79,410 | 93.65 % |
| 2025-01 | 3,475,226 | 3,475,226 | 0 | 0 | 3,177,890 | 152,379 | 144,957 | 91.44 % |

| Source file | Bronze total_amount | Silver total_amount | Gap | Valid | Suspicious | Invalid |
|---|---|---|---|---|---|---|
| 2024-12 | 103,889,786.46 | 103,889,786.46 | 0.00 | 99,175,879.76 | 6,672,877.74 | −1,958,971.04 |
| 2025-01 | 89,005,026.80 | 89,005,026.80 | 0.00 | 84,627,059.93 | 5,694,056.38 | −1,316,089.51 |

Every row and every cent of bronze is in silver; every exclusion from approved metrics is
explained by a flag (`docs/evidence/q03/recon_bronze_silver.txt`). Invalid rows carry a
negative total: they are mainly refunds and disputes (`negative_amount`: 79,303 rows in
2024-12, 144,833 in 2025-01).

**Duplicates**: 0 in both files, with the 7-column natural key. Checked independently on
the raw bronze columns of 2025-01 (0 groups). The rule stays in place for later months.

**Traceability**: trip `20250100001204` in `gold.fct_trip` is row 1204 of
`yellow_tripdata_2025-01.parquet` (pickup 2025-01-01 00:33:45, zone 79 → 107, 12.12 USD),
identical in the raw file, bronze, silver and gold.

**Volume**: bronze 2.4 GB, silver 3.2 GB, gold 2.5 GB for two months. Silver takes about
9 minutes per month on 4 GB of Docker memory.

**Failing test and response (defence)**: the first build was run on January only. The
test `assert_bronze_rows_reconcile_with_silver` failed because December was in bronze
but not in silver (`docs/evidence/q04/failing_test_reconciliation_first_build.log`). The
response was to build the missing month; the test then passed.

**Idempotence**: a second `dbt build` with no new batch processes no month
(`months to process: 1900-01-01`, a sentinel that matches no partition).

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

- `models/staging/` (views in `silver`): `stg_yellow_trips`, `stg_taxi_zones`. Snake case names, explicit casts (timestamps, `numeric(12,2)` for distance and amounts, `smallint` for codes) that return NULL instead of failing.
- `models/intermediate/` (= **silver**): `int_trips_flagged` → `silver.trips` (flags, status, deduplication), `int_trips_quarantine` → `silver.trips_quarantine`, `quality_flag_catalog`.
- `models/marts/` (= **gold**): `fct_trip`, dimensions, `agg_*`, `recon_bronze_silver`.
- `seeds/`: `us_ny_holidays` (US federal + New York State holidays, library `holidays` 0.108).
- `models/semantic/`: MetricFlow semantic models and the governed metrics (section 9).

**Monthly incremental logic** (`macros/months_to_process.sql`): a month is rebuilt when its
latest loaded batch differs from the batch already in the model, together with its two
neighbours (cross-month duplicates). The list is computed before the query and written as
date literals: PostgreSQL then prunes bronze partitions at plan time and estimates the
boundary-day filters correctly. With a subquery instead, the silver build did not finish
in 9 minutes for one month; with literals it takes about 9 minutes for two.

The `analytics` schema is written by the publication task (`airflow/include/nyc_taxi_ops/publish.py`),
**not** by dbt.

### Silver quality rules (Q3)

| Flag | Rule | Severity |
|---|---|---|
| `negative_amount` | any amount below 0 | invalid |
| `pickup_after_dropoff` | pickup strictly after dropoff (a zero-duration trip is `unrealistic_duration`) | invalid |
| `duplicate` | see below | invalid |
| `out_of_period` | pickup more than 3 days away from the file month (other year, future date) | invalid |
| `implausible_speed` | speed above 80 mph | suspicious |
| `implausible_distance` | distance above 200 miles | suspicious |
| `unrealistic_duration` | duration below 1 minute or above 6 hours | suspicious |
| `zero_distance` | distance = 0 with an amount above 0 | suspicious |
| `null_zone` | pickup or dropoff zone NULL or in {264, 265} | suspicious |
| `unknown_payment` / `unknown_ratecode` | code present but outside the known list | suspicious |
| `cross_month` | pickup within 3 days before or after the file month | info |
| `not_reported` | rate code or passenger count NULL | info |
| `component_mismatch` | `total_amount` differs from the sum of its components (± 0.05) | info |

Status: `invalid` > `suspicious` > `valid`. A row with only `info` flags stays `valid`.
Thresholds are dbt `vars`.

**One list of flags**: the macro `quality_flag_catalog()` in `dbt/macros/quality_flags.sql`
(`code, severity, description, rule, exam_requirement`) is the only place where flags are
declared. It drives the status calculation, the flag list, and the table
`silver.quality_flag_catalog` read by `dim_trip_quality`, the data dictionary and
Dashboard 5. Adding a flag means one entry in the macro and one expression in the model.

**Fare components are not additive across vendors.** Measured on 2025-01, `total_amount`
equals the sum of its components for 98.6 % of vendor 2 rows but only 9.0 % of vendor 1
rows (vendor 1 reports the congestion charges inside `extra`, typical gap 3.25 USD) and
12.1 % of rows with unreported codes (the surcharge is in the total but not in its
column, typical gap 2.50 USD). A `suspicious` flag would have rejected 32 % of trips for a
reporting convention, so `component_mismatch` is informative only. Consequences:
`total_amount` is the governed revenue measure, and any breakdown of revenue by component
(Dashboards 1 and 4) is indicative and labelled as such.

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

**Bronze → silver reconciliation**: `gold.recon_bronze_silver`, one row per source month:
file, bronze, silver and quarantine rows; rows and `total_amount` per status; rows per
flag. Tests fail when `unexplained_rows` is not 0 or `unexplained_amount` is not 0.00.

### Star schema (Q4), grain: one completed taxi trip

- `fct_trip`: `trip_sk` = YYYYMM of the source file followed by the 0-based row number on 8 digits (deterministic, readable, half the size of a hash: `20250100001204` is row 1204 of the 2025-01 file), `source_month`, `file_row_number`, `batch_id`, foreign keys (`date_sk, pickup_time_sk, pickup_zone_sk, dropoff_zone_sk, payment_type_sk, rate_code_sk, vendor_sk, service_period_sk, trip_quality_sk`), measures (fare, extra, mta_tax, tip, tolls, improvement_surcharge, congestion_surcharge, airport_fee, cbd_congestion_fee, total_amount, distance, duration_min, speed_mph, passenger_count), `is_airport_trip`, `quality_status`, `quality_flags`. Incremental `delete+insert` by `source_month`; indexes on `(date_sk)` and `(pickup_zone_sk)`, BRIN on `pickup_ts`.
- Required dimensions: `dim_date` (`is_holiday`, `holiday_name`, `is_weekend`), `dim_time`, `dim_pickup_zone` and `dim_dropoff_zone` (role-playing views of `dim_zone`: borough, zone, service_zone, `is_airport`, `is_manhattan_core`), `dim_payment_type`, `dim_rate_code`.
- Extensions: `dim_vendor`, `dim_service_period` (AM peak 7–10, PM peak 16–20, late night 0–5, off-peak), `dim_trip_quality` (junk dimension of flag combinations).
- **"Unknown" member** (key `-1`) in every dimension: NULL zones, unknown codes, dates out of range. `dim_rate_code` also has **"Not reported"** (`-2`) so the 9–16 % of trips without a rate code are not mixed with code 99.
- All foreign keys of `fct_trip` are tested with `relationships`: every trip resolves to a dimension row.
- **Full refresh** when a quality rule, a dimension or the source contract changes.

### Aggregates (sums and counts only), published in `analytics`

| Table | Grain | Used by |
|---|---|---|
| `agg_trips_daily` (179,492 rows) | day × pickup zone × payment type × rate code × vendor × status | Dashboards 1, 4, 5 |
| `agg_trips_hourly` (383,826 rows) | day × hour × pickup zone × service period × airport flag × status | Dashboards 2, 6; `trips_per_active_hour` |
| `agg_routes_monthly` (110,618 rows) | month × pickup zone × dropoff zone × service period, valid trips | Dashboards 3, 6 |
| `agg_quality_daily` (76,243 rows) | source month × day × vendor × pickup zone × payment type, trips per status and per flag | Dashboard 5 |
| `pipeline_status`, `pipeline_signals`, `recon_bronze_silver` | per publication / run / source month | "last refreshed" tile, Dashboard 5 |

**BI materialized views** (`BI_VIEWS` in `publish.py`). They are built on the published
copies (never on gold) inside the publication transaction: dropped before the swap and
recreated after it, indexed, analysed, readable by `superset_reader` and `ai_reader`.
Superset datasets point to them, so a chart reads a few thousand pre-joined rows instead of
joining the aggregates to the dimensions on every click.

| View | Rows (Dec 2024 – Feb 2025 published) | Answers |
|---|---|---|
| `mv_trips_daily`, `mv_trips_hourly`, `mv_routes_monthly`, `mv_quality_daily` | 263,323 / 591,465 / 175,616 / 113,217 | aggregates joined to their dimensions (datasets of dashboards 1 to 6) |
| `mv_revenue_bridge` | 6 | "Is revenue rising because there are more trips or higher fares?" previous revenue + volume effect + price effect = revenue, exactly (Feb 2025: 84,627,384.68 + 1,591,753.75 − 1,288,691.83 = 84,930,446.60) |
| `mv_dropoff_growth` | 164 | fastest-growing and fastest-declining drop-off zones, latest month versus the month before, zones with at least 500 trips |
| `mv_route_duration_anomaly` | 5,354 | routes slower than usual: latest month versus earlier months per route and service period (at least 100 trips in both), robust z-score `(gap − median) / (1.4826 × MAD)` across routes |

The three analyses are derived indicators built from governed metrics; they are labelled
"Derived indicator (not a governed metric)" in Superset.

### dbt tests

`unique` and `not_null` on every key, `accepted_values` on codes, `relationships` from the
fact to the dimensions, business assertions (no row lost between bronze and silver; every
`valid` trip respects the agreed thresholds), source `freshness` on the ingestion manifest
(warn 45 days, error 75 days since the last successful load). Possible next steps: enforced contracts
on marts, dbt unit tests on the flag logic, volume test against the previous month.
**Blocking tests are on silver**: when one fails, dbt skips every gold model downstream.

### Macros (Q4.5)

`quality_flag_catalog()`, `quality_status()`, `quality_flag_array()` (flags declared once),
`safe_smallint()`, `safe_amount()`, `has_cast_error()` (casts that never fail),
`safe_divide()`, `months_to_process()` and `date_literals()` (shared monthly incremental
logic), `service_period_sk()`, `generate_schema_name()`.

### Exposures and documentation

`models/exposures.yml` declares the six Superset dashboards and the AI assistant as dbt
`exposures`, so the lineage graph goes from the source file to the dashboard (Q11). The
generated documentation site (models, sources, tests, lineage) is exported to
`docs/dbt_docs/` (open `index.html`); the data dictionary `docs/data_dictionary.md` is
generated from it by `scripts/data_dictionary.py` (descriptions from the YAML, types from
the warehouse).

The macro `test_scope()` (with dbt's `get_where_subquery` hook) makes the tests of the trip
tables read the month a run loads, set by the DAG through the variable `test_month`: the
month itself for `fct_trip`, with its neighbours for bronze and silver; by default the
latest loaded month; `all` for every month.

---

## 9. Semantic layer and governed metrics (Q6)

**Built**: `dbt/models/semantic/_semantic_models.yml` (7 semantic models: trips on
`fct_trip`, pickup and dropoff zones, payment types, rate codes, vendors, calendar days,
plus the MetricFlow time spine) and `dbt/models/semantic/_metrics.yml` (15 governed metrics,
including the 12 required, and 10 base metrics used as numerators and denominators).
In dbt 1.12 a ratio metric takes metrics, not measures, as numerator and denominator:
hence the base metrics. The generated catalogue is `docs/metric_catalog.md`
(`services/metrics_sync/metrics_sync.py markdown`); the same rows go to
`semantic.metric_catalog` for the AI assistant (`... database`).

Metrics are defined in `dbt/models/semantic/*.yml` (MetricFlow), the **single source of
truth**. Each metric carries in `meta:` its `owner`, `sql_expression` (an aggregate
expression on an `analytics` table), `base_table`, `grains`, `dimensions`, `filters` and
`is_estimate`. Default owner: `AYEBIE GRAM MESCHAC`. Grains: day, week, month (and hour for
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

**Consistency test (Q6.4)**: `tests/consistency/metric_parity.py` computes eight metrics
month by month through (i) `mf query` on `fct_trip` (MetricFlow), (ii) the published SQL
read with `ai_reader` (what the AI assistant runs), (iii) the Superset chart data API. The
values must be identical; the result is written to `docs/evidence/q06/reconciliation.md`.
Last run (18 November 2026): **40/40 match on the three surfaces** (December 2024 to
February 2025 complete; the November 2024 and March 2025 stragglers are partial months that
MetricFlow and SQL agree on and Superset does not show).

**Stated limitation**: open-source MetricFlow is not queried directly by Superset. The
governed fallback is `sql_expression` with certified datasets, controlled by the
consistency test.

---

## 10. Superset and the six dashboards (Q7 and Q13)

**Built, as code** (nothing is configured by hand in the UI):

```bash
docker compose --profile core --profile bi up -d       # Superset on http://localhost:8088
# certified datasets, governed metrics, Manhattan role and RLS (idempotent)
docker compose --profile core --profile tools run --rm -e SUPERSET_URL=http://superset:8088 \
  -e SUPERSET_ADMIN_PASSWORD -e SUPERSET_READER_PASSWORD -v "$PWD:/repo" -w /repo \
  --entrypoint python ingestion services/metrics_sync/superset_sync.py
# the six dashboards; every chart's query is run and must return without error
docker compose --profile core --profile tools run --rm -e SUPERSET_URL=http://superset:8088 \
  -e SUPERSET_ADMIN_PASSWORD -e SUPERSET_READER_PASSWORD -v "$PWD:/repo" \
  -w /repo/services/metrics_sync --entrypoint python ingestion dashboards.py
```

- `infra/superset/`: image (official 6.1.0 plus the PostgreSQL driver), configuration
  (Redis caches, one MetroMove colour palette, cross filters, dashboard RBAC).
- `services/metrics_sync/superset_sync.py`: the read-only database connection
  (`superset_reader`, `analytics` only), ten certified virtual datasets on the BI
  materialized views and operational tables, and on each dataset every governed metric
  whose expression only uses its columns (23 on `trips_daily`, 11 on `trips_hourly`, 15
  on `routes_monthly`), copied from the dbt YAML. The quality dataset gets one share per
  status and flag (18), generated from its columns. The three analysis datasets (revenue
  bridge, drop-off growth, route duration anomaly) carry derived indicators, labelled as
  such. Role `Analyst Manhattan` with a row-level security rule on 5 datasets.
- `services/metrics_sync/dashboards.py`: six dashboards, 57 charts of 15 kinds (trend
  KPIs, dual-axis bars and line, rolling mean, heatmap, origin-destination matrix,
  bubble chart, treemap, revenue waterfall, growth and decline rankings, anomaly table).
  Every chart description states the strategic question it answers. Weekly charts show
  whole weeks only (dataset column `complete_week`): the partial week at the end of the
  latest month made the weekly trips KPI read "-59 %". Every dashboard has
  a header with its question, a data-quality tile, a "last refreshed" tile, date and
  borough filters, cross filters, and a short "So what?" block in plain English (bullets,
  "rose by" / "fell by" rather than signed numbers), computed from the published tables
  at build time and dated with the publication. Borough colours are fixed across
  dashboards. Unit tests check that every number quoted in a "So what?" block has a query.
- **Speed and automatic refresh**: chart results are cached for 24 hours in Redis. The
  cache key includes the dataset's last-change time. After each publication, the DAG task
  `refresh_dashboards` runs `metrics_sync.py database`, `superset_sync.py` (the datasets
  change, so the previous publication's cached results are no longer served) and
  `dashboards.py` (charts and "So what?" texts recomputed, every chart query run once to
  refill the cache). If Superset is not running at that moment the run still succeeds and
  its summary says so; trigger the `refresh_dashboards` DAG once Superset is up.
  Verified 19 November 2026: run `success` in 5 min 11 s, datasets changed at refresh time.
- Superset's web worker timeout is raised to 300 s: with the default 60 s, the single
  worker was killed while loading during a dbt build.

**Memory**: Superset and an Airflow build do not fit together in 4 GB (6 GB of swap used,
requests above 5 minutes). On the development machine, data loading and dashboard work
are done at different times; on a 16 GB host they can run together.

Superset with Redis (cache), connected with `superset_reader` to the `analytics` schema
only. **Certified** datasets, row-level security by role (for example `analyst_manhattan`
only sees Manhattan). Global date filters, cross-filters, a "last refreshed" tile, and a
drill-down path Executive → zone → hour → payment type → route.

Every dashboard has a **data-quality tile** (`valid_trip_rate` of the filtered period and
its status against the agreed threshold) and ends with a Markdown block: a plain-English
"so what?" insight and a recommended next question.

| # | Dashboard | Strategic question | Key elements |
|---|---|---|---|
| 1 | Executive Pulse | Are trips and revenue healthy? | week-over-week, month-over-month and **year-over-year** KPIs (each calendar month, one line per year), revenue decomposition (volume, distance, fare, tolls, fees), valid versus all rows, borough contribution, freshness and completeness |
| 2 | Demand Rhythm | When should capacity increase? | hour × weekday heatmap, weekday / weekend / holiday, trips per active hour by borough, peaks, seasonality versus a 3-month baseline, airport versus city |
| 3 | Geography and Routes | Where is the value moving? | choropleth map, top zones, growing and declining dropoff zones, pickup → dropoff routes, volume versus revenue per mile, airports |
| 4 | Fare, Payment and Customer | What is changing in trip economics? | fare components over time, tip rate by payment type / borough / hour / fare band, cash and card shares, rate codes, fare per mile, `cbd_congestion_fee` |
| 5 | Service Efficiency and Anomalies | Where should leaders look closer? | long durations, suspicious rate by vendor / borough / month, normal versus current duration (z-score), row counts per batch, quality threshold "pause decision" |
| 6 | City and Airport Strategy | What action should we take next? | airport demand, mix of airport / Manhattan core / outer boroughs, demand versus revenue, underserved zones (proxy), **estimated CO₂**, top three actions with validating analysis |

Year-over-year comparison became possible once thirteen months were published: two charts
of the Executive Pulse draw each calendar month with one line per year, and its "So what?"
block compares the latest month with the same month a year earlier (shown "n/a" while that
month is not published).

Evidence (`docs/evidence/q07/`): the dashboard bundle exported from Superset, screenshots,
and a note listing the governed metrics each dashboard uses.

---

## 11. AI assistant (Q8, Q9, Q10)

Stack: FastAPI (`app/api/`), React (`app/web/`), Ollama (`qwen2.5:7b`; on the Apple
silicon lab machine Ollama runs natively on the GPU, the `ollama` container stays stopped),
Pydantic v2, SQLGlot. `qwen2.5:14b` was tried and not adopted: with the whole stack running
it left too little memory and swapped.

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

### Questions about next month (forecast)

"How many trips are expected in Manhattan next month?", "Which hours will be busiest?",
"Expected revenue at JFK between 7 and 10am", "And for Queens?". Such a question never goes
through the governed templates: a forecast is an estimate, kept apart from the measures.

- **Detected and scoped by code**: forecast words with a measure or a place, or the forecast
  month itself named; place, breakdown (zone, borough, hour, day), hours, weekdays or
  weekends, top N are read from the words. A month already published stays on the governed
  path. Other measures ("average fare next month") and other months are refused with the
  reason.
- **Fixed, parameterised SQL** on the published forecast (`ml.current_forecast`, revenue
  forecast), read as `ai_reader`. The 80 % range is given only where it is valid (one
  borough, one day); a total of days or hours has none, and the answer says why.
- **Worded by the model, checked by code**: the model receives the result and key facts
  computed by code (hours and days sorted, weekday averages) and writes the answer like any
  other. Its text is kept only if every figure is in the result or the key facts, belongs to
  the zone, hour or day it is quoted with (observed and caught: "8,728 trips at the peak hour
  of 17:00" when 8,728 is 18:00), and reads as an estimate. Otherwise the text written by
  code is shown.
- **Shown as an estimate**: "Estimate · forecast" chip, provenance on the ml layer, the
  method in service and its backtest error in the limits, dedicated charts (day by day with
  the range, hourly profile with its peak, ranked zones).

### React front end: `app/web/`

Vite, TypeScript, Tailwind, TanStack Query, Recharts. Types are generated from the FastAPI
OpenAPI schema (`openapi-typescript`, `npm run types`); no API type is written by hand.
Served as static files (nginx) in Compose on http://localhost:8090. Pages:

- **Overview**: the latest published month at a glance, from the governed path.
- **Forecast**: next month per borough and day with its range, the champion and the
  backtests, forecast against actual month after month, and the month as it streams in.
- **Shift planner**: up to five zones over a window of hours: expected trips and revenue,
  the range recorded over the last eight weeks, fare, duration and distance per trip. It
  describes a zone's opportunity, shared by every taxi there; the data has no taxi or driver
  identifier, so it never claims what one taxi would earn.
- **Ask a question**: conversation with visible active filters, reset, streamed answer,
  plan and provenance, chart of the result, voice input.
- **Report builder**: specification, preview, summary, confirmation.

### Evaluation pack (Q10): `evals/cases.yaml`, at least 15 cases

Normal ×3, multi-turn follow-up ×2, ambiguous ×2, unsupported ×2, empty result, malicious
instruction, invalid date, conflicting filters, model unavailable, dashboard creation.
Fields: `expected_intent, expected_metrics, expected_filters, expected_behaviour, outcome`.
Runner: `make eval` → `docs/evidence/q10/eval_results.md`. One observed failure and its
specific fix are documented.

Latest run, 27 November 2026, on the 22 published months and after the grounding and
narrative fixes of the same day (`docs/evidence/q09/`): **20 of 20 cases pass**, median
8.6 s with `qwen2.5:7b` on the lab machine (`docs/evidence/q10/eval_mac_22months_qwen2.5-7b.md`).

---

## 12. Observability and extensions

### Observability (profile `observability`): where is the problem, and why?

```bash
docker compose --profile core --profile observability up -d   # Grafana on http://localhost:3000
```

| Signal | Tool | What it covers |
|---|---|---|
| Metrics | Prometheus + exporters | host (node-exporter), every container (cAdvisor), PostgreSQL and the **pipeline state read from the ops tables** (postgres-exporter custom queries: last run, data age, months published, dbt failures, signals, valid-trip rate, unexplained rows, ingestion batches, AI audit), Airflow and Superset (StatsD), Redis, the assistant (`/metrics`: answers, step durations, model tokens, guardrails) |
| Logs | Loki + Grafana Alloy | every container, labelled by Compose service; the assistant writes one line per answer with its trace id |
| Traces | Tempo (OpenTelemetry) | one trace per question: HTTP request, guards, plan, validate, execute (SQL), narrate; span metrics and service graph |
| Alerts | Prometheus rules + Alertmanager | 14 rules as code: stale data, valid-trip rate below 85 %, unexplained rows, failed run, failed dbt tests, slow or unavailable model, narratives replaced, memory and swap pressure, container restarts, component down, forecast drift, Kafka consumer lag |

Grafana opens on **"0. Platform overview: where is the problem?"**: one status per layer in
the order the data flows (source, transformation and quality, BI and AI, host); each tile
links to the dashboard that explains it (pipeline, data quality, infrastructure, BI, AI
assistant). Data sources are linked: a metric point opens its trace (exemplars), a trace
opens its logs, a log line opens its trace. Dashboards, data sources and alert rules are
code (`infra/observability/`; dashboards generated by `grafana/build_dashboards.py`), and the
CI checks them (`promtool`, `amtool`, generated dashboards in sync).

**Least privilege**: postgres-exporter and Grafana read the warehouse as `metrics_reader`
(database statistics, the ops tables, the publication status and the reconciliation;
refused on the business aggregates, on gold and on any write).
Tempo and Loki are not exposed outside Docker; Grafana reaches them.

**Verified (19 November 2026)**: all targets up except Redis while the BI profile is
stopped (shown as such); a question produced a Tempo trace (HTTP, `assistant.ask`,
`assistant.guards`, the audit `INSERT`) and a Loki line with the same trace id; the first
pipeline metric read showed the March run stuck in Airflow for 27 hours. The stack uses
about 650 MB with memory limits per service.

### Demand forecast (wave 7, profile `ml`)

```bash
docker compose --profile core --profile ml up -d mlflow             # http://localhost:5500
docker compose --profile core --profile ml run --rm --no-deps forecast
# replay recorded months as if forecast at the time, then check them against what happened
docker compose --profile core --profile ml run --rm --no-deps forecast --replay 2025-04 2025-05
```

On an existing warehouse, `infra/postgres/init/08_ml.sql` is applied once by hand (it runs
by itself on a new volume). In normal operation the Airflow DAG `demand_forecast` runs the
job after every publication (Airflow asset `analytics_published`).

**What is forecast**: recorded valid trips, and revenue (total amount paid, USD), per pickup
zone and hour of the next month: 260 zones × 24 hours × 30 days, the empty hours kept as
zeros. Trip volume is a proxy for demand: a ride that found no taxi leaves no trace, so the
forecast predicts recorded trips, not need.

**Three methods compete every month** (`ml/src/forecasting/`):

- the **seasonal baseline**: the zone's mean at that hour and weekday over the last four
  weeks, public holidays left out;
- the **adjusted baseline**: the same, corrected per borough by the recent trend (last two
  weeks against the two before, halved, within ±10 %) and by the change the same month
  showed a year earlier (within −20 % and +25 %), once a year of history exists;
- **LightGBM** (Poisson objective; calendar, holiday, lags at four and eight weeks,
  zone-hour level, demand tier, two-week trend, last year's same month, last month's error
  per zone and borough), with quantile models (10 % and 90 %) for its range.

The 80 % range of a baseline comes from its real errors over the six previous months, by
level of the forecast.

**Rolling backtests, never a random split**: each of the last three months is forecast from
the weeks before it, the model trained on the earlier months only. A challenger replaces
the seasonal baseline only if it wins most months, has the better mean error and is not
worse on the busiest zones (92 % of trips); among those that qualify, the lowest mean error
wins. Error is WMAPE (defined with zero hours, weighted by trips),
reported per borough, per demand tier (high ≥ 20 trips an hour, medium ≥ 2, low ≥ 0.2,
sparse below) and per borough and day; sparse zones are flagged low confidence, never
hidden in an average.

First run, on six months of history (two methods then):

| Test month | Baseline, zone-hour | Model, zone-hour | Baseline, borough-day | Winner |
|---|---|---|---|---|
| March 2025 | 19.2 % | 21.0 % | 6.9 % | baseline |
| April 2025 | 19.4 % | 21.7 % | 5.2 % | baseline |
| May 2025 | 21.3 % | 20.8 % | 11.7 % | model |

The model won one month in three, so **the baseline is in service** and LightGBM stays the
challenger, retrained and tested every month. Revenue: the model won none of the three months
(mean error 24.4 % against 22.3 %). The 80 % range held 85.9 % of the zone-hours of May.
Negative result kept: a four-week trend feature made May worse and was removed.

Forecast published for **June 2025**: 3.85 million trips, 111.0 million USD.

**MLflow** (experiments `demand_forecast`, `revenue_forecast`; backend in PostgreSQL
`mlflow_meta`, artefacts in RustFS): each run records the data publication, the months, the
decision and its reasons, a fingerprint of the code, the settings, the scores of every
backtest and the model. Every model version gets the alias `challenger`; `production` only
while the model is the champion.

**Forecast against actual, month after month** (`check.py`): when a month is published (by
the batch pipeline, after its stream), the job first compares the published forecast of
that month with what was recorded, before replacing it: error, bias, 80 % coverage per
zone-hour, borough, tier and borough-day, against the error the backtests promised. A month
more than 1.5 times above it (and 3 points) is flagged as **drift**. Results stay in
`ml.forecast_check*` and on the MLflow run that made the forecast. April and May were
replayed (forecast again from the months before them only) to start the history:

| Month | Error per borough and day | Promised | Bias | Days in the 80 % range | Verdict |
|---|---|---|---|---|---|
| April 2025 | 5.2 % | 6.9 % | +0.6 % | 43 % | as expected |
| May 2025 | 11.7 % | 6.0 % | −6.6 % | 76 % | **drift** |

What the check found: in May activity rose and the four-week baseline lagged behind it (17
to 24 % too low outside Manhattan, Brooklyn −23.9 %), while the Memorial Day weekend was
forecast too high; in April the borough-day range was too narrow (calibrated on one test
month only). Revenue: April 6.1 % (promised 10.2 %), May 14.6 % (promised 8.2 %), drift.

**Learning from the gap.** The check feeds the next forecast in three ways:

1. last month's error of the baseline, per zone and per borough, is a model feature
   (recomputed for every backtest origin, so the backtests use it too);
2. LightGBM's training rows are weighted by age, half-life six months, three months when
   one of the last two checks was a drift: the model forgets an outdated pattern faster;
3. the champion is chosen again every month on fresh backtests, and the range calibrated
   again on the latest errors.

The half-life is logged in MLflow (`half_life_months`) and printed by the job with the
latest checks.

**Negative result kept.** Correcting the baseline directly by last month's error made it
worse (14.5 % against 12.9 % per borough and day over the published months): most monthly
errors come from seasonal changes (back to school in September, the holidays) that do not
carry over to the next month. That error stays a model feature only. The two-week trend
and last year's same month each improved it (12.6 % and 12.5 %; January 2026 from 20.7 %
to 16.0 %), hence the adjusted baseline. To measure the three methods on every published
month:

```bash
docker compose --profile core --profile ml run --rm --no-deps forecast --compare-baselines
```

**Replay of 18 months with the three methods** (`--replay 2025-04 … 2026-09`: each month
forecast again from the months before it only, then checked; error per borough and day):

| Period | Seasonal baseline alone | Champion chosen each month |
|---|---|---|
| April 2025 to September 2026 (18 months) | 12.4 % | 12.2 % |
| April to September 2026 | 11.4 % | **9.2 %** |
| July to September 2026 | 15.1 % | **10.1 %** |

Champions: the baseline 10 times, the adjusted baseline twice, LightGBM 6 times (from
March 2026, once a full year of history gives it last year's same month). Five of the
first ten months drifted; none since February 2026. The choice has a cost: the adjusted
baseline, better on its backtests, did worse in August 2025 (16.7 % against 13.4 %) and
February 2026 (15.4 % against 10.8 %). Revenue, replayed the same way: 13.6 % with the
baseline alone against 11.2 % with the champion over April to September 2026, no drift
since February 2026. The October 2026 forecast is LightGBM's (backtests: 22.1 % per zone
and hour against 26.6 % for the baseline).

A forecast month with no recorded trip is not checked (`check.NotRecorded`): during the
calendar gap below, February 2026 had been checked against an empty month (error NaN,
judged "ok"). That row is kept; wherever a month has several checks, a measured one
stands for it (`check.MEASURED_FIRST`, the API and the drift alert).

**The check found a calendar gap.** From February 2026 the job kept forecasting the same
month: `dim_date` ended on 31 January 2026 (`calendar_end`), so later trips were given the
Unknown date (-1), passed every relationship test and disappeared from the published views.
The calendar now runs to December 2027 and `assert_valid_trips_have_a_calendar_date`
blocks a publication in which a valid trip has no date. Repair on an existing warehouse:
`dbt seed --select us_ny_holidays`, then `dbt run --select dim_date fct_trip+` with the
affected source months **and the month before the first one** (`--vars '{months: [...]}'`):
the test's first run caught a January 2026 trip that started at 00:45 on 1 February.

**Alerts** (Prometheus, shown in Grafana): `ForecastDrift` when the latest check of a
target is a drift (from `ml.forecast_check_run`, through postgres-exporter), and
`KafkaConsumerLag` when the stream consumer falls behind (kafka-exporter).

The forecast is used by the **Forecast** page, the **Shift planner** and forecast questions
in the assistant (section 11).

### Streaming (wave 8, profile `stream`)

```bash
docker compose --profile core --profile stream up -d kafka stream-consumer kafka-ui
# Kafka UI: http://localhost:8085 (bound to localhost: it has no login of its own)
docker compose --profile core --profile stream run --rm --no-deps stream-producer \
    produce --month 2025-06 --speed 4320        # a day every 20 seconds, the month in 10 minutes
```

On an existing warehouse, `infra/postgres/init/09_stream.sql` is applied once by hand.

The TLC publishes a month about two months late. The stream shows the current month as it
happens, before the official file, without ever mixing provisional rows with the governed
measures.

- **Kafka 3.9 in KRaft mode** (one broker, no ZooKeeper). Topic `trips.yellow.raw`: three
  partitions keyed by pickup zone (a zone's trips stay in order), kept three days; dead
  letters in `trips.yellow.dlq`, kept thirty days.
- **Producer** (`services/stream`): replays the monthly file in pickup order, faster than
  real time, idempotent and compressed (lz4).
- **Contract `yellow_trip/v1`**: structure and impossible values are rejected (unknown
  schema, missing field, wrong type, unknown zone, impossible distance or amount) to the
  dead-letter topic and `stream.yellow_trips_rejects` with the reason. Business quality (a
  negative total, a zero distance) is not a rejection: the quality flags judge it later.
- **Consumer**: batches written in one transaction; offsets committed to Kafka only after
  the database; the trip key (source month, row of the file, as in bronze) makes a
  redelivery a no-op. At least once delivery, exactly once rows.
- **Provisional by construction**: `stream.yellow_trips` is in its own schema, written by the
  role `streamer` only; never in silver, `fct_trip` or a metric. Once the official month is
  published, readers ignore it.
- **Live view** (Forecast page, refreshed every 10 seconds): trips received against the
  forecast of the same days, counted with the plausibility rules of silver (distance,
  duration, speed, known zones), complete days only.

**June 2025 replayed** at 4,320 times real time: 4,322,960 trips sent in about ten minutes,
74 rejected by the contract (distances above 100,000 miles in the source file), the rest
stored once. After five complete days, June ran 4.9 % above its forecast, consistent with
the drift found in May. When the official June file is published, the forecast job checks
June against it and forecasts July: the loop continues.

Change from the original plan: no Schema Registry. With one producer and one consumer, the
contract is a versioned JSON schema checked in code, with a dead-letter topic; Avro with a
registry is the step for several independent producers.

### Machine learning: the data is heavily imbalanced, so the method must be careful

Measured on the loaded months, the data is skewed in every direction that matters for ML:

| Imbalance | Measured | Risk if ignored |
|---|---|---|
| Quality classes | about 91 % valid, 5 % suspicious, 4 % invalid | a classifier of "bad" trips scores 91 % accuracy by predicting "valid" for everything |
| Payment types | 70 % card, 11 % cash, 15 % not reported | tip models learn the card population only |
| Geography | demand concentrated in Manhattan and the airports; many outer-borough zones have few or zero trips per hour | a demand model fits Manhattan and is meaningless elsewhere; zero-inflated targets |
| Time | strong hour-of-day and weekday cycles, holidays, a new CBD fee from 2025-01-05 | random splits leak the future into training |

Rules for any model in this project:

1. **Time-based splits only** (train on past months, validate on the next ones). Never a random split of trips.
2. **Baseline first**: every model is compared with a seasonal naive forecast (same hour, same weekday, previous weeks). A model that does not beat it is not published.
3. **Metrics that respect the imbalance**: for demand counts, MAE and WMAPE (MAPE is undefined on zero-trip hours), reported per borough and per demand band, not only overall. For rare-class detection (anomalies, invalid trips), precision-recall AUC, precision at k and recall per class, never accuracy alone.
4. **Imbalance handled explicitly**: class weights or threshold tuning on a validation month for classifiers; for zones, either a model per demand tier or a pooled model with zone features, with sparse zones evaluated separately and flagged as low-confidence.
5. **Scope stated honestly**: trip volume is a proxy for demand (unserved demand is invisible), so a forecast predicts recorded trips, not need. Predictions carry an interval and the month range they were trained on.
6. **Minimum history**: at least six consecutive months before any forecast is shown, so that weekly seasonality and a holiday period are in the training data.

---

## 13. Orchestration and Docker Compose

### Airflow DAG `monthly_yellow_pipeline` (Q5)

Airflow 3.3.1 (LocalExecutor) with astronomer-cosmos 1.16.0. Code:
`airflow/dags/monthly_yellow_pipeline.py`, logic in `airflow/include/nyc_taxi_ops/`.

```
resolve_run → check_source → land_to_rustfs → load_bronze → anything_to_publish
  → dbt_build (Cosmos: one run task + one test task per dbt model, 47 tasks)
  → measure_signals → quality_gate_and_publish → refresh_dashboards → record_outcome_and_notify
```

| Task | What it does | Runs as |
|---|---|---|
| `resolve_run` | Target month: the `month` parameter, or two months before the run date (TLC delay). Opens a row in `ops.pipeline_runs`. | publisher |
| `check_source` | `HEAD` on the TLC file. A month not yet published fails with exit code 2 and is retried 4 times, 6 hours apart. | loader |
| `land_to_rustfs` | Download, validate (Parquet, size, SHA-256, contract, schema drift), store in RustFS. Unchanged file → `skipped_unchanged`. | loader |
| `load_bronze` | Reads the file **from RustFS**, checks its SHA-256 against the manifest, replaces the month partition in one transaction. | loader |
| `anything_to_publish` | Short circuit: if every loaded batch is already in the last publication (and no `force`), the build steps are skipped and the run ends as `nothing_new`. | publisher |
| `dbt_build` | Cosmos renders the dbt project from its manifest; each model is a `run` task followed by a `test` task. A failing test stops everything downstream. Test results are written to `ops.dbt_test_results` by a Cosmos callback. | transformer |
| `measure_signals` | Five operational signals written to `ops.pipeline_signals` (below). | publisher |
| `quality_gate_and_publish` | Gate: reconciliation without gap, no `fail` signal, no failed dbt test. Then the 14 approved tables and `pipeline_status` are copied to `analytics` and swapped in **one transaction**; `ops.publications` records the batches published. | publisher |
| `refresh_dashboards` | After a publication: metric catalogue, Superset datasets (cache invalidated) and the six dashboards rebuilt from the new data (`nyc_taxi_ops/bi_refresh.py`, scripts of `services/metrics_sync` mounted read-only). Superset not running is reported, not an error. Also a separate manual DAG of the same name. | publisher, Superset admin |
| `record_outcome_and_notify` | Trigger rule `all_done`: always runs. Decides `published`, `nothing_new` or `failed` from the warehouse state, adds the dashboards status, logs it, posts it to `NOTIFY_WEBHOOK_URL` when set, and fails the run when the outcome is `failed` or when the data was published but the dashboard refresh failed. | publisher |

**Why copies, not materialized views**: dbt replaces a table with `DROP TABLE ... CASCADE`
(checked in `dbt/include/postgres/macros/relations/table/drop.sql`), which would silently
drop any view built on a gold table. Copies keep the published state independent of the
next build.

**Scheduling and overlap**: cron `0 6 3 * *` (3rd of the month) set by `PIPELINE_SCHEDULE`;
empty means manual runs only (used while historical months are loaded). `max_active_runs=1`
so two monthly runs never overlap, one task at a time (`PIPELINE_MAX_ACTIVE_TASKS`, raise it
on a larger host) and dbt with one thread to fit the development machine, `catchup=False`,
`dagrun_timeout` 6 hours. Heartbeat and import timeouts are raised for a slow host (see the
infrastructure failure in `docs/evidence/q05/README.md`).

**Backfill and safe re-run**: trigger with `{"month": "2025-03"}` for any month, or
`{"month": "2025-03", "force": true}` to reload a file even if it did not change. Every
step is idempotent, so a re-run never duplicates anything.

**After a partial failure**: clear the failed task in the Airflow UI; the steps before it
are not redone. A batch that failed to load stays `landed` in the manifest, so the retry
picks it up. Whatever failed, `analytics` keeps the previous publication until a run
passes the gate.

**Retries**: 2 retries with exponential backoff by default (5, then 10 minutes, at most
30; in Airflow 3.3 `retry_exponential_backoff` is a multiplier, set to 2.0), 1 for dbt
tasks and publication, 4 spaced 6 hours apart for the source check.

**Verified runs (17 November 2026)**, details and logs in `docs/evidence/q05/README.md`:

| Run | Scenario | Outcome |
|---|---|---|
| `first_run_2025_01` | First task timed out reaching the Airflow API (machine under load) | `failed`: every downstream task stopped, nothing published, failure recorded and reported |
| `run_2025_01_attempt2` | Full run; `measure_signals` failed on a time-zone bug, was fixed, retried and cleared | `published`: 69/69 dbt tests passed, 5 signals ok, 14 tables published; dbt not redone after the failure |
| `rerun_2025_01_nothing_new` | Same month again | `nothing_new` in 1 min 21 s: file unchanged, 48 build tasks skipped |
| `load_2025_02` | New month; PostgreSQL crashed during the silver build on a saturated host, then a relationships test caught a missing dependency (new flag combinations tested before `dim_trip_quality` was rebuilt) | Each time the gate held (`analytics` stayed on January). After the fixes (swap, ordering, dependency) and clearing the failed tasks: `published`, 74/74 tests, 5 signals ok |

### Operational signals (Q5.4)

| Signal | Measure | Threshold | Effect |
|---|---|---|---|
| `freshness_days` | days since the last successful load | warn > 45 days | reported |
| `volume_change_vs_prior_month` | bronze rows versus the previous month | warn > 20 %, fail > 50 % | fail blocks publication |
| `rejected_row_rate` | suspicious + invalid share of silver rows | warn > 10 %, fail > 20 % | fail blocks publication |
| `late_data_rate` | cross-month rows share | warn > 0.1 % | reported |
| `dbt_test_pass_rate` | passed tests / tests run in this run | fail < 100 % | blocks publication |

Task durations are in the Airflow UI and `ops.pipeline_runs` keeps the start and end of
every run. All signals are published to `analytics` for Dashboard 5.

**CI** (`.github/workflows/ci.yml`, on every push): ruff and pytest for ingestion, the
assistant API, metrics sync, Airflow helpers, the forecasting job and the stream service;
dbt parse and the semantic manifest; Prometheus, Alertmanager and Grafana configuration.

### Services

| Service | Port | Profile | Status |
|---|---|---|---|
| postgres 16 | 5432 | core | built |
| rustfs (S3 API / console) | 9000 / 9001 | core | built |
| ingestion (one-shot job) | – | tools | built |
| airflow-init (one-shot: database migration, dbt manifest) | – | orchestration | built |
| airflow (api-server, scheduler, dag-processor) | 8080 | orchestration | built |
| superset-init (one-shot: database upgrade, admin, roles) | – | bi | built |
| superset 6.1.0 + redis | 8088 | bi | built |
| ollama (or native Ollama on Apple silicon) | 11434 | ai | built |
| api (FastAPI) | 8000 | ai | built |
| web (React, nginx) | 8090 (localhost) | ai | built |
| speech (voice input) | – | ai | built |
| mlflow | 5500 | ml | built |
| forecast (job: check, backtest, choose, publish) | – | ml | built |
| kafka (KRaft), stream-consumer, stream-producer (job) | – | stream | built |
| kafka-ui | 8085 (localhost) | stream | built |
| Prometheus, Alertmanager, Grafana, Loki, Alloy, Tempo, exporters | 9090, 9093, 3000 (localhost) | observability | built |

One-shot jobs (`airflow-init`, `superset-init`, `ingestion`, `forecast`, `stream-producer`)
exit with code 0 when done; they are not meant to stay running. Health checks on every
long-running service, named persistent volumes, `depends_on: condition: service_healthy`.

---

## 14. Build plan (16 → 30 November)

The plan as written on 16 November, kept to show how the work was organised; what was
actually built is in section 1 (the React front end was finished, so the Streamlit fallback
was never needed, and MLflow, Kafka and Grafana were all built).

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
├── infra/postgres/init/     # schemas, roles, bronze and manifest tables, ml (08), stream (09)
├── infra/mlflow/            # MLflow tracking server image
├── infra/observability/     # Prometheus, Alertmanager, Loki, Alloy, Tempo, Grafana as code
├── ingestion/               # landing, source contracts, manifest, bronze loader, tests
├── docs/
│   ├── exam/                # exam paper
│   └── evidence/            # logs, measures and screenshots per question
├── airflow/dags/            # monthly_yellow_pipeline.py, demand_forecast.py
├── dbt/                     # models/{staging,intermediate,marts,semantic}, macros, tests, seeds
├── ml/                      # forecasting job: data, features, model, pipeline, check, store, tracking
├── services/metrics_sync/
├── services/stream/         # Kafka producer (replay) and consumer, message contract
├── app/api/                 # FastAPI: planner, validator, resolver, guards, forecast, planner, prompts/
├── app/web/                 # React (Vite)
├── app/speech/              # speech-to-text for voice questions
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
- Year-over-year comparisons cover the months from December 2025 on (22 months loaded).
- MetricFlow is not connected directly to Superset (governed fallback and consistency test).
- The LLM can misinterpret a question: validation, provenance and human review are required.
  The number check verifies each figure and its unit, its zone, hour and month, not the
  reasoning around it.
- The forecast predicts recorded trips, not need. It has no weather or event data, so it
  still lags a sudden change; last year's same month only exists from December 2025 on.
- The shift planner describes a zone's opportunity, shared by every taxi working it: the
  data has no taxi or driver identifier, so no per-taxi earnings.
- Streamed rows are provisional and approximately filtered (no duplicate detection across
  files); only the official file is published and measured.

Future improvements: a columnar warehouse engine for larger volumes, a semantic layer
queried directly by every tool, separate environments, and a managed database and object store with backups, shared by several users.

---

## 18. Next step

1. October 2026 is loaded by the monthly schedule (3rd of the month, 06:00) when the TLC
   publishes it; its forecast is then checked and November forecast.
2. Final deliverables: demonstration video and submission zip (dashboard exports and evidence are in `docs/evidence/`).
3. After the exam: weather and event data for the forecast, the stream fed by a live
   source instead of a replay, a managed database and object store with backups for several
   users, separate environments.
