# Phase 1A — Implementation Report

**Date:** 2026-10-08 · **Branch:** `feature/phase-1a` · **Status:** Implemented — awaiting product-owner review
**Plan:** `PHASE_01A_PLAN.md` (approved, A15) · Phase 1B and 1C were **not** started.

---

## 1. What was implemented

| Area | Delivered |
|---|---|
| Repository & tooling | `backend/` (uv + committed `uv.lock`, Python 3.12), `Makefile`, `.env.example` (ISO 8601 durations, local-only values), `.editorconfig`, `.gitattributes`, Docker Compose (postgres 16, redis 7, mailpit, migrate, api, worker), non-root API/worker Dockerfile, role bootstrap SQL + `scripts/bootstrap_db.sh`, GitHub Actions CI |
| Backend core | App factory, `/api/v1`, env-driven `Settings` with deployed-environment safety validation, JSON logging with secret scrubbing, correlation IDs, standard envelopes and error codes, health/readiness, CORS allowlist, security headers, body-size/content-type guards |
| Configurable security settings | `SESSION_IDLE_TIMEOUT`, `SESSION_ABSOLUTE_TIMEOUT`, `EMAIL_VERIFICATION_TTL`, `PASSWORD_RESET_TTL`, `INVITATION_TTL` (approved defaults) plus `SESSION_TOUCH_INTERVAL`, throttling limits, password length limits, email retry settings — defined only in `app/core/settings.py`; a source test fails if durations appear elsewhere |
| Database & RLS | SQLAlchemy 2 models, transaction-scoped tenant/user context, three database roles, migrations `0001`–`0004` (10 tables), RLS enabled + forced with per-operation policies, least-privilege grants, append-only audit log |
| Identity | Register, verify email, resend verification, login, logout, logout-all, me, sessions list/revoke, forgot/reset/change password; Argon2id; enumeration resistance; throttling; security events |
| Sessions & CSRF | Opaque 256-bit session tokens (hash stored), HttpOnly/SameSite=Lax cookies, idle + absolute expiry, rotation and revocation; signed session-bound CSRF tokens with Origin/Referer allowlist |
| Transactional email | Notifications domain: templates (verification, account-exists, reset, password-changed, invitation, security notice), outbox written in the business transaction, after-commit Celery dispatch, system-role delivery worker with backoff and payload redaction, SMTP adapter behind a sender port, in-memory sender for tests, manual delivery sweep |
| Organizations | Create (creator = Owner, slug derivation), list, get, update; members list/update/remove; invitations create/list/revoke/accept; role rules; last-owner protection with row locks; multi-organization users |
| Authorization | Central permission matrix (organization-level, A7) and `authorize(context, permission, resource)`; non-members get 404 |
| Audit | Audit records for organization, membership and invitation changes; audit-log endpoint with filters and pagination (Owners + Admins) |
| Documentation | `docs/SECURITY.md` (new), DATABASE_SCHEMA (implemented Phase 1A columns), API_SPECIFICATION (Phase 1A reference + error codes), ARCHITECTURE (CSRF delivery), README (developer setup), PROJECT_STATUS, phase files |

API surface (23 operations): see `API_SPECIFICATION.md §3A, §4, §18`.

## 2. Verification results

All run against **PostgreSQL 16.15** and **Redis 7.0.15** with Python 3.12.3.

| Check | Result |
|---|---|
| `ruff check` (app, alembic, tests) | ✅ pass |
| `ruff format --check` | ✅ pass |
| `mypy --strict` (60 source files) | ✅ no issues |
| Test suite | ✅ **141 passed**, 0 failed (unit 60 · API 42 · security 30 · migrations 4 · workers 5) |
| Coverage — overall | ✅ **98.5 %** (gate 85 %) |
| Coverage — security-critical (`core/security`, `identity`, organization permissions/tenancy) | ✅ **98 %** (gate 95 %) |
| Migrations | ✅ upgrade → downgrade → upgrade on an empty database; models match migrations (no autogenerate drift) |
| RLS catalog | ✅ every table with `organization_id` (plus `organizations`) has RLS enabled + forced and policies |
| Role attributes | ✅ no superuser/BYPASSRLS/CREATEDB/CREATEROLE; all tables owned by `advegax_migrator`; no runtime UPDATE/DELETE/TRUNCATE on `audit_logs` |
| Tenant isolation | ✅ route sweep over all 9 organization-scoped operations (generated from OpenAPI) → 404; foreign child IDs → 404; raw-SQL RLS tests (no context → 0 rows; context A never sees/writes B; cross-tenant UPDATE blocked; pooled-connection context does not leak) |
| Dependency audit | ✅ `pip-audit`: no known vulnerabilities |
| End-to-end (manual) | ✅ uvicorn + real Celery worker + SMTP server: register → email delivered via SMTP → verify → login → create organization → `/auth/me` shows Owner membership; no tokens or passwords in logs |

## 3. Deviations from the plan

| # | Deviation | Reason / impact |
|---|---|---|
| 1 | The CSRF cookie is **HttpOnly** and the token is returned in response bodies (plan: non-HttpOnly cookie) | The app (`app.`) cannot read cookies set by the API host (`api.`), so the token must come from the response body. HttpOnly is strictly safer. |
| 2 | `user_action_tokens.organization_id` / `invitation_id` added in migration `0002` (plan listed the table in `0001`) | Foreign keys to `organizations`/`invitations` require those tables to exist first. |
| 3 | Added `user_action_tokens.invalidated_at` and `invitations.accepted_by_user_id` | Needed to invalidate superseded links and to record who accepted an invitation. Documented in DATABASE_SCHEMA. |
| 4 | `email_outbox.status` has no `sending` state | Delivery locks the row (`FOR UPDATE SKIP LOCKED`), which prevents double sends without an extra state. |
| 5 | Added settings `SESSION_TOUCH_INTERVAL` (5 min), `EMAIL_MAX_ATTEMPTS`, `EMAIL_RETRY_BASE_DELAY`, `THROTTLE_FAIL_OPEN` (default false) | Implements plan behaviour ("touch at most every 5 min", retries) as configuration rather than constants. Throttling fails closed (503) if Redis is down. |
| 6 | No `email-validator` dependency; email validation is in-house (`identity/emails.py`) | Kept to the approved dependency list. |
| 7 | Authorization denials are written to structured logs, not `audit_logs` | The denial aborts the business transaction; a separate-transaction audit write is a small follow-up (listed in §5). |
| 8 | A successful password reset also marks the email as verified | The reset link proves control of the address. |
| 9 | Health endpoints live under `/api/v1/health/*` | Consistent with the versioned API prefix. |
| 10 | Tests use a PostgreSQL **superuser** connection for inspection only | FORCE RLS hides rows from every non-superuser role, including the owner; inspection needs to bypass RLS. Never used by application code. |

Resolved library versions (from `uv.lock`): FastAPI 0.142.4, Starlette 1.7.0, SQLAlchemy 2.1.4, Pydantic 2.13.5, Alembic 1.20.0, psycopg 3.3.6, Celery 5.6.3, redis-py 8.1.0, argon2-cffi 25.1.0, Jinja2 3.1.6.

## 4. Not verified in this environment

| Item | Why | How it will be verified |
|---|---|---|
| Docker image build and `docker compose up` | No Docker daemon available in the build environment | CI `docker` job; first local run by the product owner/developer |
| gitleaks secret scan | Tool not installed locally (a pattern scan found nothing) | CI `security` job |
| GitHub Actions CI | No GitHub remote yet | Runs on the first push |

## 5. Known limitations and follow-ups

1. Authorization denials are logged but not stored in `audit_logs` (deviation 7).
2. No automatic email-outbox sweep until the Phase 1B scheduler; use `python -m app.workers.email_tasks`.
3. Global identity tables have no RLS by design (`SECURITY.md §4`).
4. Starlette emits a deprecation warning about `httpx` in its test client (third-party; no impact on the application).
5. Email deliverability (SPF/DKIM) and provider choice depend on Q16 (hosting).

## 6. Files

- Added: `backend/**` (application, migrations, tests, lockfile), `infrastructure/docker/**`, `scripts/bootstrap_db.sh`, `.github/workflows/ci.yml`, `docker-compose.yml`, `Makefile`, `.env.example`, `.editorconfig`, `docs/SECURITY.md`, `docs/phases/PHASE_01A_REPORT.md`.
- Modified: `.gitignore`, `README.md`, `docs/MASTER_SPECIFICATION.md` (A15), `docs/DATABASE_SCHEMA.md`, `docs/API_SPECIFICATION.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_STATUS.md`, `docs/ROADMAP.md`, `docs/phases/PHASE_01_FOUNDATION.md`, `docs/phases/PHASE_01A_PLAN.md`.
- Deleted from the project: **none**. (A temporary Git bundle used to transfer the repository and a local Redis dump file created during testing were removed; neither was ever part of the project.)
