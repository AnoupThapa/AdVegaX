# AdVegaX

AI-powered E-commerce Advertising & Growth Operating System — an independent multi-tenant SaaS that connects commerce platforms (Shopify, WooCommerce), advertising platforms (Google Ads, Meta) and analytics (GA4) into one controlled, auditable growth system.

**Status:** Phase 1A (platform core & identity) implemented — awaiting product-owner review. Phase 1B and 1C not started. See `docs/PROJECT_STATUS.md`.

## Documentation (`docs/`)

| File | Purpose |
|---|---|
| `MASTER_SPECIFICATION.md` | Product, MVP, principles, AI safety, commercial requirements, approved decisions (§20) |
| `PROJECT_RULES.md` | Permanent rules for AI coding agents and developers |
| `ARCHITECTURE.md` | System, backend, frontend, integration, AI and deployment architecture |
| `DATABASE_SCHEMA.md` | PostgreSQL entities, indexes, RLS and security rules |
| `API_SPECIFICATION.md` | Versioned REST API, validation, authorization, idempotency |
| `DISCOVERY_REPORT.md` | Architecture assessment, risks, contradictions, open decisions |
| `ROADMAP.md` | Phases, dependencies, milestones, per-phase workflow |
| `PROJECT_STATUS.md` | Current progress, decision log, open questions |
| `SECURITY.md` | How security controls are implemented and tested |
| `phases/` | One plan per phase; `PHASE_01A_PLAN.md` (approved), `PHASE_01A_REPORT.md` (implemented), `PHASE_01B_PLAN.md` (draft) |

## Local development (backend)

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 16, Redis 7 — or Docker.

**With Docker**

```bash
docker compose up --build        # postgres, redis, mailpit (http://localhost:8025), migrations, api (:8000), worker
```

**Without Docker** (PostgreSQL and Redis running locally)

```bash
cp .env.example .env                                   # local values only; never commit .env
PGUSER=postgres PGPASSWORD=... scripts/bootstrap_db.sh advegax advegax_test advegax_migration_test
cd backend
uv sync
set -a; . ../.env; set +a
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --port 8000
uv run celery -A app.workers.celery_app:celery_app worker --loglevel=INFO
```

API docs (non-deployed environments): http://localhost:8000/api/v1/docs

**Checks**

```bash
make check     # ruff lint + format check, mypy --strict, pytest (real PostgreSQL + Redis) with coverage gates
```

Tests expect the roles and databases created by `scripts/bootstrap_db.sh` and a PostgreSQL superuser for inspection (`TEST_PG_SUPERUSER` / `TEST_PG_SUPERUSER_PASSWORD`, default `postgres`/`postgres`).
