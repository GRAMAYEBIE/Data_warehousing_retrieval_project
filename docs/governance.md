# Governance note: security, lineage and ethical use

NYC Taxi Insight Hub, MetroMove Analytics. Author and data owner: AYEBIE GRAM MESCHAC.
Exam question 11. Figures below come from the publication covering December 2024 to
February 2025; each claim points to the file or query that proves it.

## 1. Least privilege

Every program connects with its own PostgreSQL role, and each role can do one job only
(`infra/postgres/init/02_roles.sql`). No role is a superuser or can create roles or
databases.

| Role | Used by | Can | Cannot |
|---|---|---|---|
| `loader` | ingestion (Airflow tasks) | write `bronze` and `ops` | read or change silver, gold, analytics |
| `transformer` | dbt | read `bronze` and `ops`, write `silver` and `gold` | publish to `analytics` |
| `publisher` | publication gate, metrics sync | read `gold`, write `analytics` and `semantic` | change bronze, silver or gold |
| `superset_reader` | Superset | `SELECT` on `analytics` only | read gold, silver, bronze or ops |
| `ai_reader` | AI assistant queries | `SELECT` on `analytics` and `semantic`; read-only transactions, 10 s statement limit | write anything, read gold or raw data |
| `ai_audit_writer` | AI assistant audit | `INSERT` into `ops.ai_audit_log` only | read the log or any data |

Effective privileges, read from `information_schema.role_table_grants` on 19 November
2026, match this table exactly (for example `ai_reader`: `SELECT` on `analytics` and
`semantic`, nothing else; settings `statement_timeout=10s`,
`default_transaction_read_only=on`). Airflow and Superset keep their own state in separate
databases (`airflow_meta`, `superset_meta`) that the warehouse roles cannot open.

Inside Superset, dashboards and datasets are certified, and the role `Analyst Manhattan`
sees Manhattan pickups only (row-level security on five datasets,
`services/metrics_sync/superset_sync.py`). The assistant creates dashboards through the
service account `ai_builder` as **drafts**; nothing is published without an explicit
confirmation (`POST /reports/{id}/confirm` with `confirm=true`).

## 2. Secrets and configuration

- Passwords, API tokens, keys and model settings live only in `.env`, which is
  git-ignored. Compose passes them to the containers; no secret is written in code, SQL or
  YAML (`02_roles.sql` reads passwords with `\getenv`).
- `.env.example` is the redacted configuration: every secret is the placeholder
  `change_me`. A test run by the CI on every push fails if a real value appears there
  (`scripts/test_bootstrap.py::test_public_env_example_holds_no_real_secret`).
- `scripts/bootstrap.py env` creates `.env` with a different random secret for every
  value and a valid Fernet key; it never overwrites an existing `.env`.
- The commit procedure scans the staged files for the values of `.env` before every
  commit (a manual step today; a pre-commit hook would make it automatic).
- The assistant API requires a bearer token (`API_TOKEN`); `/health` is the only open
  endpoint.

## 3. Lineage and visibility

**From the raw file to the chart.** Every trip keeps the position it had in its source
file: `trip_sk = YYYYMM × 10^8 + file_row_number` (for example `20250100001204` is row 1,204
of the January 2025 file). The file itself is kept unchanged in the landing zone with its
SHA-256 (`ops.ingestion_manifest`), bronze stores the raw values with `source_month`,
`batch_id` and `file_row_number`, and silver, `fct_trip` and the aggregates carry the same
key or the source month. The dbt documentation (`docs/dbt_docs/index.html`) draws the graph
from the source to every model and, through `dbt/models/exposures.yml`, on to the six
dashboards and the AI assistant.

**Metric definitions are visible where numbers are read.** Each governed metric is written
once in `dbt/models/semantic/_metrics.yml` (formula, filters, unit, owner) and copied, not
rewritten, to:

- the metric catalogue `docs/metric_catalog.md` and the table `semantic.metric_catalog`;
- Superset, where each metric carries its description and certification;
- every AI answer, whose provenance lists the definition, the SQL expression, the source
  months, the publication time, the filters and the rendered query.

The same metric returns the same value in MetricFlow, the published SQL and Superset:
40 of 40 values match (`docs/evidence/q06/reconciliation.md`).

**Data quality is visible to end users.** Every dashboard opens with a data-quality tile
(valid-trip rate of the filtered period) and a "last refreshed" tile. Dashboard 5 shows
the quality flags, the bronze to silver reconciliation (0 unexplained rows) and the
pipeline signals of each run. Every AI answer states the valid-trip rate of the months it
used.

**Nothing unchecked reaches users.** The publication gate copies gold to `analytics` only
after the whole dbt build, the reconciliation and the operational signals pass; otherwise
users keep the previous publication. After a publication, Superset's datasets, cache and
dashboards are refreshed by the same Airflow run.

## 4. The assistant cannot invent numbers or run arbitrary queries

- The language model only writes a plan (which metric, which filters, which period).
  Code validates the plan against the governed vocabulary and builds the SQL from approved
  templates; the model never writes SQL.
- The SQL is parsed (SQLGlot): one `SELECT`, `analytics` tables only, a `LIMIT`. It runs as
  `ai_reader` (read-only, 10 s).
- Questions that ask to change data or rules are refused before the model is called.
  Topics the data cannot answer (driver earnings, wait times, cancellations, rider
  identity, profit) are refused with the reason.
- The model's narrative is checked against the result: a number that is not in the result,
  or a "highest/lowest" claim the result contradicts, replaces the narrative with a factual
  summary. Two real cases were caught on 19 November 2026 (Bronx revenue written as
  $38,280.41 instead of $382,800.41; Queens trips written as 2.49 million instead of
  249,175).
- Every question is recorded in `ops.ai_audit_log`: plan, verdict, reasons, rendered SQL,
  row count, narrative check, step durations, model usage and trace id.

## 5. Using the data fairly and honestly

**Observational data, not experiments.** Trip records show what happened, not why. A
change after the congestion fee started (5 January 2025) is a correlation; weather,
holidays and other transport also changed. Dashboards say "associated with", not
"caused by", and the "So what?" blocks end with the next question that would test a cause.

**Proxies are named as proxies.**

| Shown | What it really measures | How it is labelled |
|---|---|---|
| Trips | completed Yellow Taxi trips, not demand: riders who found no taxi are invisible | "trip volume as a demand proxy" in dashboards 2 and 6 and in the AI limitations |
| Tip rate | tips on card payments only (cash tips are not recorded) | "card trips only" in the metric name and definition |
| Estimated CO2 | distance × 0.400 kg/mile (US EPA typical car), not a measurement | "ESTIMATE" in the metric name, warning in Superset and the AI answer |
| Underserved zones | low Yellow Taxi volume | "what additional data would be needed" stated next to the table |

**Under-coverage and data errors.** The data is reported by vendors and TLC does not
guarantee it. In February 2025, 90.5 % of trips are valid and 5.1 % are invalid (mostly
negative amounts: refunds and disputes); over the three months, 15.6 % of trips have no
payment type reported. Invalid
trips are kept in silver with their flags and excluded from governed metrics, never
silently deleted; suspicious ones are kept and counted separately. Decisions pause when
the valid-trip rate falls below 85 % or a pipeline signal fails.

**Geographic fairness.** Yellow taxis serve mostly Manhattan and the airports: 90.2 % of
valid pickups are in Manhattan, and the segment "outer boroughs and upper Manhattan" is
only 5.2 % of trips. Green taxis
and for-hire vehicles (Uber, Lyft), which serve the outer boroughs more, are not in this
data. Consequences applied in the platform:

- low Yellow volume in a borough is never presented as low need; dashboard 6 recommends
  adding Green taxi and for-hire data and wait times before any service decision;
- rates on small groups are unstable, so rankings use minimum volumes (500 trips for
  zone growth, 100 trips for route anomalies) and sparse zones are flagged;
- the planned forecasting work evaluates error per borough, not only overall, so the
  model cannot look good by fitting Manhattan alone (README, machine learning rules).

## 6. Human review

| Situation | Who decides | What the platform does |
|---|---|---|
| Valid-trip rate below 85 % or a failed signal | data owner | publication blocked or flagged; dashboard 5 lists the reason |
| A question the data cannot answer | analyst | the assistant refuses and says why |
| A dashboard created by the assistant | manager | stays a draft until explicitly confirmed |
| A narrative with an unsupported number or ranking | none needed | replaced automatically, kept in the audit log for review |
| A conclusion about a cause or about outer-borough service | manager with additional data | dashboards state the limit and the data needed |

## 7. Known limits

- The audit log and Superset hold question texts; they contain no personal data because
  the source has none (no rider or driver identifier), but access to them should stay
  with the data team.
- Secrets are environment variables, not a secret manager; a production deployment would
  use one (for example Docker secrets or a vault) and rotate them.
- Row-level security is demonstrated with one role; a real deployment would map roles to
  MetroMove teams.
