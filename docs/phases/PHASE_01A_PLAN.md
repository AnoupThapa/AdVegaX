# Phase 1A — Platform Core & Identity: Implementation Plan

**Status:** Awaiting product-owner approval · **Date:** 2026-10-08
**Depends on:** Phase 0 (closed) · **Followed by:** Phase 1B (integration foundation), Phase 1C (frontend shell)
**Governing documents:** MASTER_SPECIFICATION §20–§21 (D1–D22, A1–A14), PROJECT_RULES, ARCHITECTURE §3, §5–§8, DATABASE_SCHEMA §0–§3, §16, §19, API_SPECIFICATION §1–§4, §18, §24

> No application code is written until the product owner explicitly approves this plan. Items marked **[Default — confirm]** are proposed defaults the product owner may change in the approval.

---

## 1. Objective

Build the secure foundation every later phase depends on: a production-grade backend skeleton with PostgreSQL Row-Level Security, AdVegaX's own identity system (email + password, email verification, server-managed sessions, CSRF), transactional email, organizations with memberships, invitations and organization-level roles, an append-only audit log, and CI that proves tenant isolation and security properties on every change.

At the end of 1A a user can, **through the API**:
register → verify email → sign in → create an organization (becoming Owner) → invite a member → the invitee accepts → roles are managed → sessions can be listed and revoked → every material event is audited — with no external platform connected.

## 2. Scope

| Area | In scope |
|---|---|
| Repository & tooling | Monorepo skeleton (backend only), `.env.example`, `Makefile`, Docker Compose for local development, dependency locking |
| Backend core | App factory, `/api/v1`, settings, structured JSON logging, correlation IDs, error envelope, health endpoints, CORS allowlist, security headers |
| Database | SQLAlchemy 2 base and mixins, unit of work with transaction-scoped tenant context, Alembic, database roles, RLS policies, Phase 1A tables (§6) |
| Identity | Register, verify email, resend verification, login, logout, logout-all, me, sessions list/revoke, forgot/reset/change password |
| Sessions & CSRF | Opaque session cookie, idle/absolute expiry, rotation, revocation; CSRF tokens + Origin checks; authentication throttling |
| Transactional email | Notifications domain: templates, outbox (same transaction), Celery delivery worker, sender port with SMTP adapter, local mail catcher |
| Organizations | Create/list/get/update organizations, members list/update/remove, invitations create/list/revoke/accept, last-owner protection |
| Authorization | Central permission matrix (organization-level, A7) and `authorize(context, action, resource)` |
| Audit & security events | Append-only audit log for material actions; security events for authentication; audit-log read endpoint |
| CI | Lint, format, type check, tests, migration checks, RLS catalog check, secret scan, dependency audit, image build |
| Documentation | `docs/SECURITY.md` (new), schema/API updates, README developer setup, status updates |

## 3. Non-goals (explicitly excluded from 1A)

- Frontend (Phase 1C).
- External connections, credential encryption, provider framework, SSRF client, job-run framework, scheduler (Phase 1B).
- Any real platform integration, webhooks, product/order/ad data, finance, AI, billing (later phases).
- Google/Microsoft/enterprise login, MFA, passkeys (designed for only — A8).
- Resource-level permissions or their UI (A7).
- `idempotency_keys`, `webhook_events`, `sync_runs` tables (introduced with their first real use — A4).
- Production deployment and hosting choice (D9).

## 4. Dependencies

### 4.1 Platform versions **[Default — confirm]**
Python 3.12 · PostgreSQL 16 · Redis 7 · Docker Engine with Compose v2.

### 4.2 Runtime Python packages (11)
`fastapi`, `uvicorn` (ASGI server), `pydantic`, `pydantic-settings`, `sqlalchemy` (2.x, synchronous), `alembic`, `psycopg` (v3), `argon2-cffi`, `celery`, `redis`, `jinja2` (email templates).
SMTP uses the standard library. No auth, CSRF or rate-limit libraries — these are small, security-critical and kept explicit and tested in-house.

### 4.3 Development packages (5)
`pytest`, `pytest-cov`, `httpx` (FastAPI test client), `ruff` (lint + format), `mypy`.

### 4.4 Tooling **[Default — confirm]**
`uv` for dependency resolution and a committed lockfile (alternative: `pip-tools`). Local mail catcher: Mailpit container (development only).

### 4.5 Design choice: synchronous SQLAlchemy
Synchronous SQLAlchemy 2 with psycopg 3 in FastAPI's threadpool. Reason: simpler, well-understood transaction semantics for `SET LOCAL` tenant context, and the same code path as Celery workers (also synchronous). Async can be revisited if measured load requires it.

### 4.6 External prerequisites
- GitHub remote for `advegax` (product owner) — required for CI to run; local development and tests do not depend on it.
- No platform credentials needed. Email in development goes to the local mail catcher.

## 5. Proposed files and directories

```text
advegax/
├── .gitignore                      (exists after Phase 0)
├── .env.example                    variable names + safe local defaults only
├── .editorconfig
├── Makefile                        up, down, migrate, test, lint, format, typecheck, check
├── docker-compose.yml              postgres, redis, mailpit, api, worker
├── infrastructure/docker/
│   ├── api.Dockerfile              multi-stage, non-root
│   └── postgres/init/001_roles.sql creates advegax_migrator / advegax_app / advegax_system for local & CI only
├── .github/workflows/ci.yml
├── docs/SECURITY.md                new (sessions, CSRF, RLS roles, secrets, logging rules)
└── backend/
    ├── pyproject.toml  uv.lock  alembic.ini
    ├── alembic/env.py  alembic/versions/0001…0004
    ├── app/
    │   ├── main.py                         app factory, middleware, routers
    │   ├── core/
    │   │   ├── settings.py                 env-driven settings + production safety validation
    │   │   ├── logging.py                  JSON logs, secret scrubbing
    │   │   ├── correlation.py              request/correlation ID middleware
    │   │   ├── errors.py                   error envelope, exception handlers
    │   │   ├── security/                   passwords.py, tokens.py, csrf.py, cookies.py, throttle.py, headers.py
    │   │   └── clock.py                    injectable clock (testable expiry)
    │   ├── db/
    │   │   ├── base.py  mixins.py          UUID PK, timestamps
    │   │   ├── session.py                  engines (app / system roles)
    │   │   └── unit_of_work.py             transaction + SET LOCAL tenant/user context
    │   ├── api/
    │   │   ├── router.py                   /api/v1
    │   │   ├── deps.py                     current_session, current_user, tenant_context, require_permission, csrf
    │   │   └── health.py
    │   ├── domains/
    │   │   ├── identity/                   models, schemas, repository, service, router
    │   │   ├── organizations/              models, schemas, repository, service, router, permissions.py
    │   │   ├── audit/                      models, service (append-only), router (read)
    │   │   └── notifications/              email/ (port.py, smtp.py, console.py), templates/, outbox model, service
    │   └── workers/
    │       ├── celery_app.py
    │       └── email_tasks.py
    └── tests/
        ├── conftest.py  factories.py
        ├── unit/  integration/  api/  security/  migrations/  workers/
```

## 6. Database tables (Phase 1A only)

All tables: UUID primary keys (generated by the application), `created_at`/`updated_at` in UTC (`timestamptz`), explicit constraints, every foreign key indexed.

| Table | Purpose | Class (DATABASE_SCHEMA §19) | Key constraints / indexes |
|---|---|---|---|
| `users` | AdVegaX identity | Global identity | unique index on `lower(email)`; `status` check |
| `user_password_credentials` | Password hash, separate from user (future IdPs/MFA) | Global identity | PK = `user_id` FK |
| `sessions` | Server-side sessions | Global identity | unique `token_hash`; index `(user_id, revoked_at)`; expiry checks |
| `user_action_tokens` | Single-use tokens: email verification, password reset, invitation | Global identity | unique `token_hash`; `purpose` check; index `(user_id, purpose)`; `organization_id` + `invitation_id` for invitation tokens |
| `organizations` | Tenant | Organization | unique `slug`; `default_currency` ISO-4217 check; `default_timezone` validated in app |
| `memberships` | User ↔ organization with role | Membership | unique `(organization_id, user_id)`; `role`, `status` checks; index `(user_id, status)` |
| `invitations` | Pending invites | Tenant-owned | index `(organization_id, status)`; partial unique `(organization_id, lower(email))` where pending |
| `audit_logs` | Append-only audit | Tenant-owned (nullable org for user-level events) | index `(organization_id, created_at)`; no UPDATE/DELETE grants |
| `security_events` | Authentication/security events | Security/system | index `(user_id, created_at)`, `(event_type, created_at)`; insert-only for app |
| `email_outbox` | Transactional email outbox | Security/system | index `(status, next_attempt_at)`; app insert-only; system role processes |

Relationships: `memberships.user_id → users`, `memberships.organization_id → organizations`, `invitations.organization_id → organizations`, `invitations.invited_by_user_id → users`, `user_action_tokens.user_id → users`, `user_action_tokens.invitation_id → invitations`, `sessions.user_id → users`. Invariant enforced in the service with a locking check: each organization keeps ≥ 1 active Owner.

## 7. Migrations

| Migration | Contents | Downgrade |
|---|---|---|
| `0001_identity` | users, user_password_credentials, sessions, user_action_tokens; grants to `advegax_app` | drop in reverse |
| `0002_organizations` | organizations, memberships, invitations; RLS enabled + forced; policies; grants | drop policies, tables |
| `0003_audit_security` | audit_logs, security_events; RLS/policies; restricted grants (no UPDATE/DELETE on audit) | drop |
| `0004_email_outbox` | email_outbox; role-specific policies (app insert, system process) | drop |

Rules: run as `advegax_migrator`; database roles are **not** created by migrations (cluster-level; local/CI via `001_roles.sql`, hosted environments via infrastructure later) — migrations fail with a clear error if roles are missing; every migration is reversible and tested; one linear history; no data migrations needed (greenfield).

## 8. API endpoints (Phase 1A)

As specified in API_SPECIFICATION §3–§4 and §18:

| Group | Endpoints | Auth | CSRF |
|---|---|---|---|
| Health | `GET /health/live`, `GET /health/ready` | none | — |
| CSRF | `GET /auth/csrf` | none | — |
| Registration | `POST /auth/register`, `POST /auth/verify-email`, `POST /auth/resend-verification` | none / session for resend | yes |
| Session | `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /auth/me`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}` | session (except login) | yes on state change |
| Password | `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/change-password` | none / session | yes |
| Organizations | `GET/POST /organizations`, `GET/PATCH /organizations/{id}` | session + verified email to create | yes |
| Members | `GET /organizations/{id}/members`, `PATCH/DELETE …/members/{member_id}` | session + role | yes |
| Invitations | `POST/GET /organizations/{id}/invitations`, `DELETE …/invitations/{invitation_id}`, `POST /invitations/accept` | session + role; accept: session + matching verified email | yes |
| Audit | `GET /organizations/{id}/audit-logs` | Owner/Admin | — |

All responses use the standard envelope; errors never include stack traces; non-members receive 404 for organization routes; insufficient role receives 403.

## 9. Authentication and session architecture

| Element | Design |
|---|---|
| Passwords | Argon2id via `argon2-cffi` (library defaults following RFC 9106; parameters stored in the hash; transparent rehash on login if parameters change). Length 12–128 characters; no composition rules; reject the user's email as password. |
| Registration | Always returns the same accepted response. New email → account + verification email. Existing email → no change; a "you already have an account" email is sent instead. |
| Unverified accounts **[Default — confirm]** | May sign in, but cannot create organizations or accept invitations until verified. |
| Session token | 256-bit random; only SHA-256 hash stored; cookie value is the raw token. |
| Cookie | Name env-configured (`__Host-advegax_session` in staging/production); `HttpOnly`, `Secure` (required outside local), `SameSite=Lax`, `Path=/`, host-only on the API host. |
| Lifetimes **[Default — confirm]** | Idle timeout 24 h (sliding, updated at most once per 5 min to limit writes); absolute lifetime 14 days. |
| Rotation & revocation | New session on login and on password change; reset-password and logout-all revoke every session; individual session revocation; revoked/expired sessions rejected server-side on every request. |
| Assurance | Session stores `auth_method` and an assurance level so MFA/step-up can be added later (A8). |
| Single-use tokens **[Default — confirm]** | Email verification 24 h, password reset 30 min, invitation 7 days; hashed at rest; consumed atomically; older tokens of the same purpose invalidated when a new one is issued. |
| Throttling **[Default — confirm]** | Redis fixed-window counters: login 5/min per account+IP and 20/min per IP; register 5/h per IP; forgot-password and resend-verification 3/h per email and 10/h per IP. Responses do not reveal which limit triggered beyond a generic 429. |
| Enumeration resistance | Uniform responses and comparable work (password hash performed against a dummy hash for unknown emails). |
| Auditing | Security events for every login success/failure, logout, logout-all, session revocation, password reset request/completion, password change, email verification. |
| Separation | Authentication (identity domain) yields `Principal(user_id, session_id)`. Authorization (organizations domain) turns `Principal + organization_id` into `TenantContext(org_id, user_id, role)`. |

## 10. Email / transactional email architecture

```text
identity / organizations service
   └─ notifications.send(template, recipient, variables)   (domain call; no vendor knowledge)
        └─ INSERT email_outbox (same DB transaction as the business change)
             └─ after commit: enqueue Celery task deliver_email(outbox_id)
                  └─ worker (advegax_system role): render Jinja2 template → EmailSender port → SMTP adapter
                       └─ mark sent / schedule retry with exponential backoff / mark failed after N attempts
```

- Templates (text + HTML) in Phase 1A: `email_verification`, `password_reset`, `account_exists`, `invitation`, `password_changed`, `security_notice` (e.g. all sessions revoked).
- Sender port with adapters: `SmtpSender` (configurable host/port/TLS/credentials) and `ConsoleSender` (tests). Vendor choice later (Q16) without code changes in identity/organizations.
- Links built only from the environment-configured `APP_BASE_URL`; tokens never logged; outbox payload readable only by the system role.
- **Known gap until 1B:** if enqueue fails right after commit, the row stays `pending`. 1A provides a management command to deliver pending emails; 1B's scheduler adds an automatic sweep.

## 11. Organization and membership model

- Creating an organization makes the creator its **Owner** (single transaction, audited).
- Roles: Owner, Admin, Manager, Analyst, Viewer (API §24). Owner/Admin manage members and invitations; only an Owner can grant or remove the Owner role; the last active Owner cannot be removed, demoted or leave.
- Invitations: email + role; inviter cannot grant a role higher than their own; one pending invitation per email per organization; accept requires the signed-in user's **verified** email to equal the invited email; acceptance creates the membership and consumes the token atomically.
- Membership status: active / suspended / removed (removal is soft so audit history stays meaningful).
- Users can belong to multiple organizations (schema and API support it from day one — D11); `GET /organizations` lists the user's active memberships.
- Future: agency grants (Phase 14) and resource-level permissions (A7) attach to this model without changing it.

## 12. Tenant context

- Every `/organizations/{organization_id}/…` request: session → `Principal` → membership lookup for that organization (active) → role → `TenantContext`. Not a member → **404**. The URL organization ID is only a claim.
- `UnitOfWork(context)` opens a transaction and runs `set_config('app.current_org_id', …, true)` and `set_config('app.current_user_id', …, true)` (transaction-local) before any query. Identity endpoints set only the user ID (or nothing for anonymous flows).
- Repositories for tenant tables require a `TenantContext` argument and refuse to run without one.
- Services call `authorize(context, action, resource)` before acting; resources are re-loaded within the tenant.
- Celery tasks receive IDs only, never context objects; each task opens its own unit of work. (General tenant-aware task base arrives in 1B.)

## 13. PostgreSQL RLS strategy

| Item | Design |
|---|---|
| Roles | `advegax_migrator` (owner, migrations only) · `advegax_app` (runtime; not owner, not superuser, `NOBYPASSRLS`) · `advegax_system` (worker/system tasks; `NOBYPASSRLS`; access granted per table/policy) |
| Enforcement | `ENABLE` + `FORCE ROW LEVEL SECURITY` on organizations, memberships, invitations, audit_logs, security_events, email_outbox |
| Context functions | Policies use `current_setting('app.current_org_id', true)` / `('app.current_user_id', true)`; unset → no rows (fail closed) |
| organizations | SELECT: `id = current_org` OR active membership of current user; INSERT/UPDATE: `id = current_org` (new organization: the service generates the ID and sets context to it inside the creating transaction) |
| memberships | SELECT: `organization_id = current_org` OR `user_id = current_user`; INSERT/UPDATE: `organization_id = current_org` |
| invitations | All: `organization_id = current_org` |
| audit_logs | INSERT: org = current_org or org NULL; SELECT: org = current_org; no UPDATE/DELETE privilege for any runtime role |
| security_events | app: INSERT only; system: SELECT |
| email_outbox | app: INSERT only; system: SELECT/UPDATE (policies `TO advegax_system`) |
| Global identity tables | No RLS (lookups happen before any user/org context, e.g. login by email). Accessible only through the identity repository; never joined into organization responses beyond membership summaries. Documented as an accepted design decision in SECURITY.md. |
| Pooling | Only transaction-local settings; session-level `SET` forbidden (lint rule + test that a reused connection has no context) |
| Bypass prevention | No `SECURITY DEFINER` functions; no `BYPASSRLS` roles; app never connects as migrator; CI checks role attributes and grants |
| Migrations | New tenant tables must ship their policy in the same migration (CI catalog check) |

## 14. Security controls

- **CSRF:** signed double-submit token — `GET /auth/csrf` sets a non-HttpOnly CSRF cookie (HMAC-signed, bound to the session once one exists); every POST/PATCH/PUT/DELETE requires a matching `X-CSRF-Token` header **and** an `Origin` in the allowlist. Login and registration are protected too (login CSRF).
- **CORS:** explicit allowlist from configuration with credentials; startup fails in staging/production if `*` or empty.
- **Settings safety:** in staging/production, startup refuses insecure cookies, debug mode, wildcard CORS, missing or default secrets.
- **Headers:** `Cache-Control: no-store` on auth and account responses; `X-Content-Type-Options: nosniff`; `Referrer-Policy`; HSTS in production (at app or proxy).
- **Logging:** JSON, correlation ID on every line; scrubber removes cookies, `Authorization`, passwords, tokens, CSRF values; user/org IDs logged, emails not.
- **Errors:** standard envelope; generic messages; internal details only in logs.
- **Secrets:** environment variables locally (`.env` git-ignored), managed secret store in hosted environments (D15); `.env.example` has names and harmless local defaults only.
- **Dependencies:** lockfile; `pip-audit` and secret scanning (`gitleaks`) in CI.

## 15. SSRF / network security foundation

Not applicable to 1A: 1A makes no outbound requests to user-supplied hosts (SMTP host is operator-configured, not user-supplied). The SSRF-safe client specified in ARCHITECTURE §9.3 is built and tested in **Phase 1B**, before any provider exists. 1A adds a CI rule that forbids direct use of HTTP client libraries outside `providers/http/` so the boundary exists from the first commit.

## 16. Testing strategy

All tests run against real PostgreSQL 16 and Redis 7 (Compose locally, service containers in CI); no database mocking for repository/RLS tests. Time-dependent behaviour uses the injectable clock.

| Layer | Examples |
|---|---|
| Unit | password hashing/rehash; token generation/hash; CSRF sign/verify; cookie attributes per environment; permission matrix; settings production validation; email template rendering; log scrubber |
| Integration (DB) | repositories; unit-of-work context; last-owner invariant under concurrent requests; token single-use under concurrency |
| API | every endpoint: valid, invalid, unauthenticated, missing/invalid CSRF, wrong tenant (404), insufficient role (403), not found, throttled |
| Workers | outbox delivery, retry/backoff, permanent failure, no token values in logs |
| Coverage gate **[Default — confirm]** | ≥ 85 % lines overall; ≥ 95 % for `core/security`, `identity`, `organizations` permission code |

### 16.1 Tenant-isolation tests
- Two-organization fixture (A and B, distinct users, shared user in both).
- **Route sweep:** every organization-scoped route called by a member of A with B's IDs (organization, member, invitation) → 404; parametrized from the router so new routes are covered automatically.
- **Raw RLS tests** as `advegax_app`: no context → zero rows on every RLS table; context A → never B's rows; INSERT with B's `organization_id` under context A → rejected.
- Shared user sees both organizations in `GET /organizations`, but data access follows the active organization context only.
- Connection-reuse test: after a transaction with context A commits, the next transaction on the same pooled connection has no context.

### 16.2 Security tests
Cookie flags; session fixation (ID changes on login); expired/revoked/idle sessions rejected; logout-all and reset revoke everything; CSRF (missing, mismatched, foreign Origin, cross-session token); CORS rejection of non-allowlisted origins; enumeration resistance (identical responses for known/unknown emails); throttling; invitation email mismatch; token reuse and expiry; privilege escalation attempts (inviting or promoting above own role, removing last owner); audit log immutability (UPDATE/DELETE denied); error responses contain no stack traces; logs contain no secrets.

### 16.3 Migration tests
`upgrade head` on an empty database → `downgrade base` → `upgrade head`; schema drift check (autogenerate produces no changes); **RLS catalog check** (every table with `organization_id` has RLS enabled + forced and at least one policy); role check (`advegax_app` not owner, not superuser, no BYPASSRLS; no UPDATE/DELETE on `audit_logs`).

## 17. CI requirements

GitHub Actions on every pull request and on `main`:

1. `ruff check` and `ruff format --check`
2. `mypy --strict` on `app/`
3. Tests with PostgreSQL 16 + Redis 7 service containers (roles bootstrapped from `001_roles.sql`), coverage gate
4. Migration job: up/down/up, drift check, RLS catalog and role checks
5. Security: `gitleaks` secret scan, `pip-audit`
6. Build the API Docker image (non-root)

Branch protection on `main` (product owner): PRs only, all checks required. CI runs once the GitHub remote exists; until then the same checks run locally with `make check`.

## 18. Documentation changes

- `docs/SECURITY.md` (new; justified by A8–A11): sessions, CSRF, cookie policy, RLS roles and table classes, secret handling, logging rules, accepted risks.
- `DATABASE_SCHEMA.md`: final Phase 1A columns, constraints and indexes.
- `API_SPECIFICATION.md`: request/response schemas and error codes for 1A endpoints.
- `ARCHITECTURE.md`: any refinement discovered during implementation (reported, not silent).
- `README.md`: local developer setup.
- `PROJECT_STATUS.md` and `phases/PHASE_01_FOUNDATION.md`: progress and results.

## 19. Acceptance criteria

1. `make check` passes locally; CI green once the remote exists.
2. The end-to-end API journey in §1 works against Docker Compose, with emails visible in the local mail catcher.
3. Every endpoint in §8 has tests for the cases listed in §16.
4. Tenant-isolation, security and migration test suites (§16.1–§16.3) pass.
5. `advegax_app` cannot read tenant rows without context, cannot modify audit logs, and is not owner/superuser/BYPASSRLS — verified by tests.
6. No secrets in the repository (secret scan clean); `.env.example` contains no real values.
7. Staging/production settings validation rejects insecure configuration.
8. Documentation in §18 updated; implementation report lists files changed, tests run, any deleted files (A1), known limitations.

## 20. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| RLS policy mistakes (e.g. membership/organization policies too broad) | HIGH | Raw-SQL policy tests per table and per operation; review of every policy in PR |
| Global identity tables without RLS | MEDIUM | Single identity repository; route sweep tests; documented accepted risk |
| Session/CSRF misconfiguration across `app.`/`api.` subdomains | HIGH | Cookie/CSRF tests per environment profile; staging verification before production |
| Last-owner race (two owners demote each other) | MEDIUM | Row locks (`SELECT … FOR UPDATE`) on the organization's owner memberships |
| Outbox enqueue gap until 1B scheduler | LOW | Manual delivery command; sweep in 1B |
| Email deliverability (SPF/DKIM) in hosted environments | MEDIUM | Addressed with provider choice (Q16) before staging |
| Timing differences enabling account enumeration | LOW | Dummy-hash path; tests compare responses |
| CI unavailable until GitHub remote exists | LOW | `make check` locally; remote to be created by product owner |
| Windows host line endings/permissions in the shared folder | LOW | `.gitattributes` enforcing LF; development inside containers |

## 21. Rollback considerations

- Greenfield: no production data or users exist; nothing to migrate back.
- All work on a feature branch merged by pull request; rollback = revert the merge.
- Every migration has a tested downgrade; `downgrade base` restores an empty schema.
- Database roles are created idempotently by the bootstrap script and never dropped by migrations.
- No external systems are touched (email only to the local catcher in development).

## 22. Decisions requested with approval

| # | Item | Proposed default |
|---|---|---|
| 1 | Platform versions | Python 3.12, PostgreSQL 16, Redis 7 |
| 2 | Dependency tooling | `uv` + lockfile |
| 3 | Session lifetimes | idle 24 h, absolute 14 days |
| 4 | Token lifetimes | verification 24 h, reset 30 min, invitation 7 days |
| 5 | Throttling limits | as in §9 |
| 6 | Unverified accounts | may sign in; cannot create organizations or accept invitations |
| 7 | Audit-log access | Owner and Admin |
| 8 | Coverage gate | 85 % overall, 95 % security-critical |
| 9 | New document | `docs/SECURITY.md` |
