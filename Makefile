# AdVegaX developer commands. Backend commands run from backend/ with uv.
.PHONY: up down bootstrap-test migrate test lint format typecheck check

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
		--include="app/core/security/*,app/domains/identity/*,app/domains/organizations/permissions.py,app/domains/organizations/tenancy.py"

lint:
	$(BACKEND) uv run ruff check app alembic tests
	$(BACKEND) uv run ruff format --check app alembic tests

format:
	$(BACKEND) uv run ruff format app alembic tests
	$(BACKEND) uv run ruff check --fix app alembic tests

typecheck:
	$(BACKEND) uv run mypy

check: lint typecheck test
