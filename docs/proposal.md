# NYC Taxi Insight Hub: proposal (Q1)

**For** MetroMove Analytics (operations, planning and commercial managers) and its technical team.
**Author** AYEBIE GRAM MESCHAC (roll number 2000250045) · DS6102 · November 2026

> **In short.** MetroMove receives a large monthly file of taxi trips but cannot tell quickly
> whether demand is changing, which zones need attention or whether an odd fare is a data error.
> NYC Taxi Insight Hub turns each file into one trusted set of figures, published only after
> quality checks, shown in six dashboards and explained by an AI assistant that can only use
> those approved figures. Success is measured by five targets, each checked by the platform itself.

## 1. Problem and decisions

Every month the city's taxi regulator (TLC) publishes about four million Yellow Taxi trips,
two months after the month ends. Today each team cleans the file its own way, so the same
question gets different answers, and nobody can say where a number came from or whether it
can be trusted. Managers end up debating the numbers instead of the decisions.

The platform serves four groups, each with a decision it should make faster and better:

| Users | Decision the platform should improve, and a typical question |
|---|---|
| Operations leaders | **Capacity planning**: where and when to place taxis. *"Which zones will be busiest between 17:00 and 20:00 next month?"* |
| City planners | **Zone monitoring**: which zones gain or lose trips, and when a trend breaks. *"Which drop-off zones are declining fastest?"* |
| Commercial analysts | **Fare-policy review**: effect of the congestion fee (since 5 January 2025), airport fees, tips. *"How much revenue does the fee represent, and where?"* |
| Data team | **Quality triage**: *"Is this unusual fare a data error or a real event, and can we still publish the month?"* |

**What changes for the client**: one answer per question, published within an hour of the
file, with its definition, its source month and its quality level visible next to it.
**Out of scope**, because the data cannot support it: driver earnings, rider identity,
waiting time, cancellations, real emissions and profitability.

## 2. Why the warehouse, governed metrics and BI come before the AI assistant

An assistant is only as trustworthy as the numbers beneath it, so the platform is built in
that order. **The warehouse** keeps one copy of every trip, raw then cleaned, and checks that
no row is lost: anyone can trace a figure back to its row in the original file. **Governed
metrics** give each measure ("revenue", "trips", "tip rate") one written definition used by
every tool, so a dashboard and the assistant cannot disagree. **Dashboards** let managers see
and question these figures before any AI is involved. **The AI assistant** comes last, with
narrow rights: it chooses which approved measure answers a question and explains the result;
it never writes the query that runs and never calculates, and code checks that every figure
in its text comes from the approved result.

Starting with the AI would invert this: it would invent its own definitions, give figures
that do not match the dashboards, and its mistakes would be invisible because nothing
trusted would exist to compare them with.

**For the technical team**: an S3 landing zone, a PostgreSQL warehouse in bronze, silver,
gold and analytics layers built with dbt, Apache Airflow running the month from download to
publication, a semantic layer of 15 governed metrics, Apache Superset, and a FastAPI
assistant using a local model (Ollama) that may read the published layer only, through a
read-only role. Everything runs in Docker Compose, started with one command.

## 3. Success measures

Each measure has a target, a way of measuring it that does not depend on anyone's opinion,
and a result. The data team reviews them every month after the publication (Grafana and
Dashboard 5); a missed target is investigated before the next month is published.

| Area | Measure and target | How it is measured · result so far |
|---|---|---|
| **Data freshness** | A month is published **the day its file is detected**: **≤ 1 h** from the source check to publication; the data age is shown on every dashboard and answer | Airflow run times and the data-age metric in Grafana · about 20 min per monthly run |
| **Data quality** | Valid-trip rate **≥ 85 %** per month; **0** rows unexplained between raw and cleaned data; **0** failed blocking test before publication | Reconciliation table and dbt tests at every run · 90 % to 94 % per month; every row explained; publication refused when a test fails |
| **Dashboard usefulness** | Every chart answers a named business question and each dashboard ends with a "so what" insight; **100 %** of charts return data; the same metric gives the **same value** in every tool | Automatic check of every chart; parity test across tools · 6 dashboards, all charts returning data; 40 of 40 metric checks identical |
| **AI answer trustworthiness** | **100 %** of figures in an answer come from an approved query; **≥ 90 %** of the evaluation cases pass; **0** model-written SQL executed | Evaluation pack (20 cases) and audit log of every answer · 20 of 20 pass; a text quoting a figure not in the result is replaced automatically |
| **Delivery reliability** | **≥ 95 %** of monthly runs succeed without manual action; a failed run **never** changes published data; services restart on their own | Airflow run history · every month loaded in order without intervention; a deliberately failed run left published data unchanged |
| *Forecast (extension)* | Error per borough and day at or below what its backtests promised | Monthly forecast-against-actual check · June 2025: 6.0 % against 7.9 % promised |

## 4. Risks and limits that need human review

| Risk | What can go wrong | Safeguard, and when a human decides |
|---|---|---|
| **Source data quality** | Trips are reported by vendors: 9 to 16 % lack a payment type or rate code; some are impossible (distances above 100,000 miles) | Quality flags, valid-trip rate on every answer, warning below 85 %; an analyst reviews a month under the threshold or a reconciliation gap before it is used |
| **LLM-generated insight** | The model may misread a question, give a true figure to the wrong month or unit, or present a guess as a cause | The plan, filters and query are shown; figures are checked by code; explanations are labelled as hypotheses; decisions rest on the governed figure, read by a person |
| **Demand is not need** | Trips only show rides that happened, not people who found no taxi; forecasts lag a sudden trend (May 2025 was forecast 6.6 % too low) | Forecasts are labelled estimates with a range; each month is checked against reality and drift is flagged for review |
| **Geographic coverage** | Yellow taxis serve mostly Manhattan and the airports; outer boroughs look "underserved" partly because other services serve them | Zone comparisons are labelled as Yellow Taxi only; a service decision needs data from other services first |
| **Source changes** | The TLC can change the file's columns (it added the congestion fee in 2025) | The source contract rejects the month with the reason; the data team updates the contract |
| **Association is not cause** | A drop after the congestion fee does not prove the fee caused it | Dashboards show what changed; policy conclusions need an analyst's judgement |
