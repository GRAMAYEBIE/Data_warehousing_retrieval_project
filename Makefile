# NYC Taxi Insight Hub - common commands.
# On Windows without make, run the docker compose command shown under each target.

COMPOSE := docker compose
CORE    := $(COMPOSE) --profile core
TOOLS   := $(COMPOSE) --profile core --profile tools
ORCH    := $(COMPOSE) --profile core --profile orchestration
MONTH   ?= 2025-01

.PHONY: help up down ps logs ingest ingest-force zones test-ingestion lint-ingestion psql \
	airflow-up run-month run-month-force dbt-build test-ops

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

up: ## Start the core services (PostgreSQL, RustFS)
	$(CORE) up -d --wait

down: ## Stop the services (volumes are kept)
	$(COMPOSE) --profile core --profile orchestration --profile tools down

ps: ## Show service status and health
	$(CORE) ps

logs: ## Follow the service logs
	$(CORE) logs -f

zones: ## Ingest the taxi zone lookup
	$(TOOLS) run --rm ingestion zones

ingest: ## Ingest one month: make ingest MONTH=2025-01
	$(TOOLS) run --rm ingestion yellow --month $(MONTH)

ingest-force: ## Re-ingest one month even if the source is unchanged
	$(TOOLS) run --rm ingestion yellow --month $(MONTH) --force

test-ingestion: ## Unit tests of the ingestion package
	$(TOOLS) run --rm --no-deps --entrypoint pytest ingestion -q -p no:cacheprovider

lint-ingestion: ## Lint and format check of the ingestion package
	$(TOOLS) run --rm --no-deps --entrypoint sh ingestion -c "ruff format --no-cache --check src tests && ruff check --no-cache src tests"

airflow-up: ## Start the core services and Airflow (UI on http://localhost:8080)
	$(ORCH) up -d --wait

run-month: ## Run the whole pipeline for one month in Airflow: make run-month MONTH=2025-02
	$(ORCH) exec airflow-scheduler airflow dags trigger monthly_yellow_pipeline \
		--conf '{"month": "$(MONTH)", "force": false}'

run-month-force: ## Same, reloading the file even if it did not change
	$(ORCH) exec airflow-scheduler airflow dags trigger monthly_yellow_pipeline \
		--conf '{"month": "$(MONTH)", "force": true}'

dbt-build: ## Build and test the dbt project outside Airflow
	$(TOOLS) run --rm dbt build

test-ops: ## Unit tests of the pipeline operations logic (signals, gate, dbt results)
	$(TOOLS) run --rm --no-deps -v "$(CURDIR)/airflow:/airflow" -e PYTHONPATH=/airflow/include \
		--entrypoint pytest ingestion -q -p no:cacheprovider /airflow/tests

psql: ## Open psql on the warehouse as the admin user
	$(CORE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
