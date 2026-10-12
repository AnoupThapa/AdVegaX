# AdVegaX developer commands. Backend commands run from backend/ with uv.
.PHONY: up down bootstrap-test migrate test lint format typecheck check frontend-install frontend-check frontend-dev e2e

BACKEND = cd backend &&

up:            ## start the local stack (Docker)
	docker compose up --build -d

down:
	docker compose down

bootstrap-test: ## create roles + test databases on a local PostgreSQL (needs superuser env: PGUSER/PGPASSWORD)
	scripts/bootstrap_db.sh advegax_test advegax_migration_test

migrate:
	$(BACKEND) uv run alembic upgrade head

test:
	$(BACKEND) uv run pytest --cov=app --cov-branch --cov-report=term-missing --cov-fail-under=85
	$(BACKEND) uv run coverage report --fail-under=95 \
		--include="app/core/security/*,app/domains/identity/*,app/domains/organizations/permissions.py,app/domains/organizations/tenancy.py,app/providers/http/*,app/domains/integrations/credentials.py,app/domains/integrations/connect_state.py"

lint:
	$(BACKEND) uv run ruff check app alembic tests
	$(BACKEND) uv run ruff format --check app alembic tests

format:
	$(BACKEND) uv run ruff format app alembic tests
	$(BACKEND) uv run ruff check --fix app alembic tests

typecheck:
	$(BACKEND) uv run mypy

check: lint typecheck test

# Frontend (Phase 1C) — Node.js 24 LTS, run from frontend/
FRONTEND = cd frontend &&

frontend-install:
	$(FRONTEND) npm ci

frontend-check: ## lint, format, strict type check, unit tests with coverage, production audit, build
	$(FRONTEND) npm run check
	$(FRONTEND) npm run build

frontend-dev:
	$(FRONTEND) npm run dev

e2e: ## end-to-end + accessibility tests (needs the running stack — see README)
	$(FRONTEND) npm run e2e
