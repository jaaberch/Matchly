# Matchly developer commands.
# Everything here works from a clean checkout with Docker installed.

COMPOSE ?= docker compose
API     := $(COMPOSE) exec -T api
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip

.DEFAULT_GOAL := help
.PHONY: help up down restart logs ps build bootstrap migrate migration seed reset \
        test test-pg lint fmt shell psql redis worker-ping openapi

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	 | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Docker stack ─────────────────────────────────────────────────────────────
up: ## Start the full development stack
	$(COMPOSE) up -d --build
	@echo "API   http://localhost:8000/docs"
	@echo "Web   http://localhost:3000"
	@echo "MinIO http://localhost:9001"

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

restart: ## Restart the application services
	$(COMPOSE) restart api video-worker ai-worker beat web

build: ## Rebuild images
	$(COMPOSE) build

logs: ## Tail logs (make logs S=api)
	$(COMPOSE) logs -f $(S)

ps: ## Show service status
	$(COMPOSE) ps

# ── Database ─────────────────────────────────────────────────────────────────
migrate: ## Apply database migrations
	$(API) alembic upgrade head

migration: ## Autogenerate a migration (make migration M="add venues.city")
	@test -n "$(M)" || (echo "usage: make migration M=\"describe the change\"" && exit 1)
	$(API) alembic revision --autogenerate -m "$(M)"

seed: ## Load the demo match (idempotent)
	$(API) python -m app.seed

reset: ## Drop the database, re-migrate and re-seed
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres redis minio minio-init api
	sleep 5
	$(MAKE) migrate seed

# ── Local development (no Docker) ────────────────────────────────────────────
bootstrap: ## Create a local virtualenv and install everything editable
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "packages/shared[s3,postgres]"
	$(PIP) install -e "apps/api[dev]"
	$(PIP) install -e services/video-worker -e services/ai-worker
	@echo "Done. Activate with: source $(VENV)/bin/activate"

# ── Quality ──────────────────────────────────────────────────────────────────
test: ## Run the test suite (SQLite; no services needed)
	cd apps/api && ../../$(PY) -m pytest -q

test-pg: ## Run the same suite against PostgreSQL (needs TEST_DATABASE_URL)
	cd apps/api && ../../$(PY) -m pytest -q

lint: ## Lint Python
	$(VENV)/bin/ruff check apps/api packages services
	$(VENV)/bin/ruff format --check apps/api packages services

fmt: ## Format Python
	$(VENV)/bin/ruff check --fix apps/api packages services
	$(VENV)/bin/ruff format apps/api packages services

# ── Handy ────────────────────────────────────────────────────────────────────
shell: ## Shell inside the API container
	$(COMPOSE) exec api bash

psql: ## PostgreSQL prompt
	$(COMPOSE) exec postgres psql -U matchly -d matchly

redis: ## Redis prompt
	$(COMPOSE) exec redis redis-cli

worker-ping: ## Check that both workers are consuming
	$(COMPOSE) exec -T video-worker celery -A video_worker.worker:app inspect ping

openapi: ## Write the OpenAPI schema to openapi.json
	cd apps/api && ../../$(PY) -c "import json;from app.main import app;print(json.dumps(app.openapi(), indent=2))" > ../../openapi.json
	@echo "wrote openapi.json"
