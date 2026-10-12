# AdVegaX

AI-powered E-commerce Advertising & Growth Operating System — an independent multi-tenant SaaS that connects commerce platforms (Shopify, WooCommerce), advertising platforms (Google Ads, Meta) and analytics (GA4) into one controlled, auditable growth system.

**Status:** Phase 1 (foundation) implemented — 1A platform core & identity, 1B integration foundation (test platform only), 1C web application — awaiting product-owner review. Real platform integrations not started. See `docs/PROJECT_STATUS.md`.

## Documentation (`docs/`)

| File | Purpose |
|---|---|
| `AI_CONTEXT.md` | Start here (AI agents): current state, rules, task and report templates |
| `MASTER_SPECIFICATION.md` | Product, MVP, principles, AI safety, commercial requirements, approved decisions (§20) |
| `PROJECT_RULES.md` | Permanent rules for AI coding agents and developers |
| `ARCHITECTURE.md` | System, backend, frontend, integration, AI and deployment architecture |
| `DATABASE_SCHEMA.md` | PostgreSQL entities, indexes, RLS and security rules |
| `API_SPECIFICATION.md` | Versioned REST API, validation, authorization, idempotency |
| `DISCOVERY_REPORT.md` | Architecture assessment, risks, contradictions, open decisions |
| `ROADMAP.md` | Phases, dependencies, milestones, per-phase workflow |
| `PROJECT_STATUS.md` | Current progress, decision log, open questions |
| `SECURITY.md` | How security controls are implemented and tested |
| `INTEGRATION_GUIDES.md` | How a platform connector is added; per-provider notes |
| `phases/` | One plan per phase; `PHASE_01A_PLAN.md` (approved), `PHASE_01A_REPORT.md` (implemented), `PHASE_01B_PLAN.md` (approved), `PHASE_01B_REPORT.md` (implemented), `PHASE_01C_PLAN.md` (approved), `PHASE_01C_PROGRESS.md` (task reports), `PHASE_01C_REPORT.md` (implemented) |

## Local development (backend)

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), PostgreSQL 16, Redis 7 — or Docker.

**With Docker**

```bash
docker compose up --build        # postgres, redis, mailpit (http://localhost:8025), migrations, api (:8000), worker, beat (scheduler), web (:3000)
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
uv run celery -A app.workers.celery_app:celery_app beat --loglevel=INFO   # scheduler (email sweep, job recovery)
```

API docs (non-deployed environments): http://localhost:8000/api/v1/docs

## Local development (frontend)

Requirements: Node.js 24 LTS (`frontend/.nvmrc`).

```bash
cd frontend
cp .env.example .env.local        # public values only (NEXT_PUBLIC_API_BASE_URL)
npm ci
npm run dev                       # http://localhost:3000
```

Checks: `make frontend-check` (ESLint, Prettier, strict TypeScript, Vitest with coverage, production dependency audit, build).

**End-to-end and accessibility tests** (Playwright + axe) run against a real stack. Start PostgreSQL, Redis, Mailpit, the API and a worker (as above, or `docker compose up`), build and start the web app (`npm run build && npm start`), then:

```bash
cd frontend
npx playwright install chromium   # once
npm run e2e                       # or: make e2e
```

The suite creates several accounts from one address, so give the local API higher sign-up/sign-in limits (e.g. `THROTTLE_REGISTER_PER_IP_PER_HOUR=100`, `THROTTLE_LOGIN_PER_IP_PER_MINUTE=100`, `THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE=30`, `THROTTLE_EMAIL_ACTION_PER_IP_PER_HOUR=100`) — CI does the same. Addresses can be changed with `E2E_WEB_URL`, `E2E_API_URL`, `E2E_MAILPIT_URL`; a pre-installed Chromium with `PLAYWRIGHT_CHROMIUM_EXECUTABLE`.

The local test platform's sign-in page (`fake-platform.invalid`) does not exist; the suite answers it the way an approving user would. Real platforms are not connected in Phase 1.

API types: after changing the backend API, run `uv run python -m app.api.openapi_export` (in `backend/`) and `npm run api:generate` (in `frontend/`). Tests on both sides fail while the committed schema or types are out of date.

**Checks**

```bash
make check     # ruff lint + format check, mypy --strict, pytest (real PostgreSQL + Redis) with coverage gates
```

Tests expect the roles and databases created by `scripts/bootstrap_db.sh` and a PostgreSQL superuser for inspection (`TEST_PG_SUPERUSER` / `TEST_PG_SUPERUSER_PASSWORD`, default `postgres`/`postgres`).
