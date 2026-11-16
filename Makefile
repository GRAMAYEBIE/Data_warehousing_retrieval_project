# NYC Taxi Insight Hub - common commands.
# On Windows without make, run the docker compose command shown under each target.

COMPOSE := docker compose
CORE    := $(COMPOSE) --profile core
TOOLS   := $(COMPOSE) --profile core --profile tools
MONTH   ?= 2025-01

.PHONY: help up down ps logs ingest ingest-force zones test-ingestion lint-ingestion psql

help: ## List the available targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

up: ## Start the core services (PostgreSQL, RustFS)
	$(CORE) up -d --wait

down: ## Stop the services (volumes are kept)
	$(TOOLS) down

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

psql: ## Open psql on the warehouse as the admin user
	$(CORE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
