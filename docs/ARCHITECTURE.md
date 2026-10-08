# AdVegaX — System Architecture Specification

> **Amended 2026-10-08** to reflect product-owner decisions D1–D22 (MASTER_SPECIFICATION.md §20) and the Phase 0 approval record A1–A14 (§21).

## 1. Architecture Style

Use a **modular monolith** for MVP.

One deployable backend can contain strongly separated domain modules. This reduces operational complexity while preserving boundaries for future extraction.

## 2. High-Level Architecture

```text
Browser
  |
  v
Next.js / React / TypeScript
  |
  v
FastAPI Application
  |
  +-- Auth / RBAC
  +-- Organizations / Tenancy
  +-- Commerce Domain
  +-- Advertising Domain
  +-- Analytics Domain
  +-- Funnel Domain
  +-- Finance Domain
  +-- AI Domain
  +-- Recommendation / Action Engine
  +-- Audit Domain
  +-- Billing Domain
  |
  +---- PostgreSQL
  +---- Redis
  +---- Background Workers
  |
  +---- Commerce providers (Shopify GraphQL Admin API, WooCommerce REST API)
  +---- Google Ads API
  +---- Meta Marketing API
  +---- Google Analytics Data API
```

## 3. Repository Structure

Domain-first modular monolith (approved, A3). Directories are created only when the phase that needs them is implemented.

```text
advegax/
├── README.md  .gitignore  .env.example  docker-compose.yml  Makefile
├── docs/                         # specifications, roadmap, status, phase plans (+ SECURITY.md, ADR/ when justified)
├── backend/
│   ├── pyproject.toml  alembic.ini
│   ├── alembic/                  # migrations (single linear history)
│   ├── app/
│   │   ├── main.py               # application factory
│   │   ├── core/                 # settings, logging, errors, correlation IDs, security primitives (CSRF, hashing), clock
│   │   ├── db/                   # engine, unit of work, tenant-context setter, base model and mixins
│   │   ├── api/                  # /api/v1 router composition and shared dependencies (session, tenant, permission)
│   │   ├── domains/              # one package per bounded context: models, schemas, repository, service, router, permissions
│   │   │   ├── identity/         # users, credentials, sessions, action tokens          (Phase 1)
│   │   │   ├── organizations/    # organizations, memberships, invitations, roles         (Phase 1)
│   │   │   ├── audit/            # audit log, security events                             (Phase 1)
│   │   │   ├── notifications/    # transactional email (templates, outbox, sender port)   (Phase 1)
│   │   │   ├── integrations/     # connections, external resources, organization links  (Phase 1B)
│   │   │   └── …                 # commerce, advertising, analytics, funnel, finance, ai, strategy, creatives,
│   │   │                         # recommendations, actions, automation, billing, reporting — added in their phases
│   │   ├── providers/            # the ONLY place platform-specific code lives            (framework Phase 1B)
│   │   │   ├── base/             # interfaces, capabilities, availability, registry, error taxonomy, normalized DTOs
│   │   │   ├── http/             # SSRF-safe outbound client, rate limiter, retry policy
│   │   │   └── <category>/<provider>/   # added from Phase 2A
│   │   └── workers/              # Celery app, task base (tenant context), schedules
│   └── tests/                    # unit/ integration/ api/ security/ migrations/ (providers/ from 1B)
├── frontend/                     # Next.js App Router, TypeScript strict (Phase 1C)
│   ├── app/  features/  components/  lib/api/  hooks/  tests/
├── infrastructure/docker/        # Dockerfiles; database role bootstrap for local/CI; IaC after hosting is chosen
├── scripts/
└── .github/workflows/            # CI
```

Rules:
- A domain may call another domain only through that domain's service interface, never its repository or models directly.
- Provider-specific code never appears in `domains/`.
- Tests live with each application.

## 4. Frontend Architecture

Use feature-oriented UI.

Example:
```text
features/
├── auth/
├── dashboard/
├── products/
├── integrations/
├── campaigns/
├── creatives/
├── analytics/
├── funnel/
├── recommendations/
├── automation/
├── billing/
└── settings/
```

Frontend responsibilities:
- presentation,
- user input,
- API calls,
- client-side UX validation,
- loading/error states.

Do not place authoritative business rules only in the frontend.

## 5. Backend Layers

### API layer
HTTP concerns only.

### Application/service layer
Use-case orchestration.

### Domain layer
Business rules.

### Repository/data layer
Persistence.

### Provider layer
External APIs.

### Worker layer
Asynchronous jobs.

This separation should prevent provider-specific logic from contaminating domain logic.

## 6. Tenant Context

Each request resolves:
- authenticated principal,
- active organization,
- role,
- permissions.

The service layer must receive tenant context explicitly.

Every query involving tenant data must be tenant-scoped.

Tenant isolation is layered (Decision D12):

```text
Authentication → Authorization → Tenant Context → Repository/ORM controls → PostgreSQL RLS → Database
```

- RLS is required on every tenant-owned table and is defence in depth, not a substitute for application authorization.
- Tenant context is set per transaction (transaction-scoped), so pooled connections cannot carry it into another request.
- The application runtime role is not a superuser, does not own the tables and does not have BYPASSRLS.
- Migrations and explicitly designated system/administrative operations use separate, audited roles.
- Background workers, Celery tasks and scheduled jobs set tenant context explicitly for each unit of work.
- Cross-tenant isolation tests are mandatory.
- Tenant context carries both the organization ID and the user ID, so policies can allow a user to see their own memberships across organizations (to list and switch organizations) without exposing other tenants' data.
- Global identity tables (users, credentials, sessions, single-use action tokens) are not tenant-owned. They are reachable only through the identity domain and never exposed through organization endpoints except via membership joins. Details: DATABASE_SCHEMA.md §19.

## 7. Authentication

First version (A8): **email + password** with email verification, secure password hashing (Argon2id) and server-managed sessions. Authentication (who you are) and authorization (what you may do) are separate concerns.

Supported in Phase 1:
- account creation, email verification, login, logout, logout-all,
- password reset / account recovery, password change,
- session listing and revocation,
- authentication auditing (security events).

Model (Decision D10):

```text
Browser → HTTPS → Secure HttpOnly session cookie → FastAPI → authenticated user → organization/tenant authorization
```

- Opaque, high-entropy session identifier in a `Secure` (production), `HttpOnly`, `SameSite=Lax` cookie; only its hash is stored.
- Idle and absolute expiration; rotation on login and privilege change; revocation; logout.
- CSRF protection for every state-changing request: a signed token bound to the session, held by the web app in memory (returned in response bodies) and mirrored in an HttpOnly cookie on the API host; the `X-CSRF-Token` header must match the cookie and the signature must match the current session; plus an Origin/Referer allowlist check. Implemented in `app/core/security/csrf.py` and `middleware.py`.
- No authentication secrets or long-lived sensitive tokens in browser storage.
- Throttling per IP and per account on authentication endpoints; uniform responses that do not reveal whether an email is registered.

**Extensibility without redesign.** Credentials are separate from the user record: a password credential now; external identities (Google, Microsoft, enterprise SAML/OIDC) and MFA factors/passkeys later as additional credential types, each added when in approved scope. Sessions record the authentication method and assurance level so step-up/MFA can be introduced later.

**Transactional email (A9).** The identity domain asks the notifications domain to send a templated message (e.g. `email_verification`); it never talks to an email vendor. Messages are written to an outbox in the same transaction and delivered by a worker through a configurable sender port (SMTP adapter first; local development uses a mail catcher). Links use the environment-configured application URL. Tokens are never logged.

**Separate security domains.** AdVegaX user authentication is independent of third-party platform authorization (Shopify, WooCommerce, Google Ads, Meta, GA4). A user can register and sign in without any external platform account and with no platform connected. Platform credentials are obtained and used only server-side, never sent to the browser or the LLM, and never act as AdVegaX login credentials.

**Future Shopify App Store channel (not MVP, A14).** If built, it is a separate entry surface that links a Shopify installation to an AdVegaX organization. It must not replace or weaken AdVegaX authentication or make the core Shopify-dependent.

## 8. Authorization

MVP authorization is **organization-level RBAC** (A7). The model keeps four concerns separate:

| Layer | Question | Phase 1 implementation |
|---|---|---|
| 1. Membership | Is the user an active member of this organization? | `memberships` (status) |
| 2. Organization role | What may this role do in this organization? | Owner / Admin / Manager / Analyst / Viewer; central permission matrix (API §24) |
| 3. Resource ownership / linking | Does this resource belong to (or is it linked to) this organization? | Tenant-scoped repositories + RLS; resources re-loaded inside the tenant |
| 4. Resource-level authorization (future) | May this user act on this specific store/ad account? | Not implemented; the `authorize(context, action, resource)` interface already receives the resource so grants can be added without redesign |

- Deny by default; checks are made in services before any business action, not only in routes.
- An organization always has at least one active Owner.
- No resource-level permission UI or tables in Phase 1.

## 9. Integration Architecture

Provider-based integration architecture is a fundamental requirement. Define provider interfaces per category:

```text
CommerceProvider
├── ShopifyProvider          (MVP)
├── WooCommerceProvider      (MVP)
└── future commerce providers

AdvertisingProvider
├── GoogleAdsProvider        (MVP)
├── MetaAdsProvider          (MVP)
└── future: TikTok, Microsoft, Amazon, LinkedIn, ...

AnalyticsProvider
├── GA4Provider              (MVP)
└── future analytics providers
```

Core business logic (finance, funnel, AI, recommendations, actions) operates only on normalized internal models. Adding a provider must not require changes to the core engines. Provider capabilities differ (e.g. not every commerce platform exposes product cost or webhooks), so each provider declares its capabilities and the core handles missing capabilities explicitly rather than assuming them.

The rest of the system should depend on interfaces/internal models, not provider SDK objects.

### 9.1 Connections, resources and links (approved, A6)

```text
User (authorizes) → External Connection (tenant-owned; credentials encrypted)
                       └── External Resources (discovered: stores, ad accounts, properties, business assets)
                              └── Organization Resource Links (explicit; history kept)
```

- A connection is created within an organization and records who authorized it.
- Discovery lists what the connection can reach; nothing is used until the organization **explicitly links** a resource.
- Unlinking and relinking create new link records rather than overwriting history, so reassignment stays auditable and isolated.
- Shopify and WooCommerce typically yield one store per connection; Google Ads and Meta can yield many ad accounts; GA4 many properties.
- **As built (Phase 1B, A16):** the organization owns the connection and a user authorizes it; the same platform account used by two organizations means two connections. Tables, composite tenant keys and RLS are in `DATABASE_SCHEMA.md §4`; endpoints in `API_SPECIFICATION.md §5`.

### 9.2 Capabilities and data availability (A10)

Each provider declares capabilities (e.g. webhooks, product cost, inventory, refund lines, validate-only, campaign creation, ecommerce events). Every normalized value that may be missing carries an availability state:

| State | Meaning |
|---|---|
| `available` | Value present and current within its freshness window |
| `unavailable` | Platform could provide it but it is not accessible for this account (permissions, missing tagging, missing cost data) |
| `unsupported` | The platform does not provide it |
| `not_synchronized` | Not yet synchronized, or stale beyond its freshness window |

Values are never converted to 0 when not `available`. Aggregations that include a non-available input report the reduced availability rather than a partial number presented as complete.

### 9.3 Outbound network security (A11)

All outbound calls to externally supplied hosts use one SSRF-safe client:
- `https` only (no other schemes; no credentials in URLs);
- hostname normalized and validated; IP literals and internal names rejected;
- DNS resolved by the client and **every** resolved address checked against blocked ranges (loopback, private, link-local, carrier-grade NAT, multicast, reserved, IPv6 unique-local/link-local, IPv4-mapped forms, cloud metadata addresses); connection pinned to the checked address to defeat DNS rebinding;
- redirects not followed automatically; each redirect target re-validated, cross-host redirects refused by default, and a small maximum hop count;
- connect/read/total timeouts and a maximum response size;
- credentials attached only after validation, never sent to a redirect target, never logged;
- egress through a dedicated network path where hosting allows (documented in DEPLOYMENT once hosting is chosen).

The client is built and tested in Phase 1B, before any provider exists (`backend/app/providers/http/`; `SECURITY.md §9`). It connects directly and ignores proxy environment variables; any egress proxy is designed with hosting (Q16).

### 9.4 Provider framework and background jobs (as built, Phase 1B)

- `app/providers/base/`: `PlatformProvider` protocol (authorization URL, complete authorization with PKCE, discover resources, sync resource, revoke), category protocols (`CommerceProvider`, `AdvertisingProvider`, `AnalyticsProvider` — filled in from Phase 2A), capability and availability types, `Money` (Decimal + ISO currency), normalized provider errors (retryable vs not), and the provider registry. Test-only providers are refused in deployed environments.
- `app/providers/fake/`: deterministic test provider with configurable failures (auth expired, permission denied, rate limited, transient failures, revoke failure). The only provider in Phase 1B.
- `app/providers/http/`: SSRF-safe client and a Redis token-bucket rate limiter per provider.
- Core domains never import provider-specific code (source test); credentials are only decrypted inside the integrations domain (source test).
- **Jobs:** `job_runs` is the source of truth. A job row is written in the business transaction and dispatched to Celery after commit; the worker claims it with `FOR UPDATE SKIP LOCKED` as the system role, then runs the handler under the job's tenant context. Retryable errors back off exponentially with jitter (respecting provider `Retry-After`) up to `JOB_MAX_ATTEMPTS`, then the job is **dead**-lettered; non-retryable errors fail immediately with a code. A periodic recovery task re-queues jobs stuck in `running` longer than `JOB_STUCK_AFTER`.
- **Scheduler:** Celery beat defines the schedule (email sweep, job recovery); each scheduled run takes a Redis `SET NX EX` lock so only one instance executes per window even if several beat processes run.

## 10. Sync Architecture

Provider data is synchronized through background jobs.

Typical flow:

```text
Scheduler
  ↓
Sync Job
  ↓
Provider Connector
  ↓
Raw Provider Response
  ↓
Normalizer
  ↓
Transactional Database
  ↓
Derived Aggregation
```

Keep enough external identifiers and timestamps to make synchronization traceable.

## 11. Action Engine

All advertising mutations must pass through the Action Engine.

```text
User/AI Request
  ↓
Schema Validation
  ↓
Business Rules
  ↓
Budget Rules
  ↓
Risk/Policy Rules
  ↓
Authorization
  ↓
Idempotency Check
  ↓
Provider Action
  ↓
Verification
  ↓
Audit Event
```

The Action Engine is the principal safety boundary between recommendations and money-moving external actions.

The Campaign Builder, optimization recommendations and autopilot all execute through the Action Engine; no other execution pathway to a platform exists (A13).

## 12. AI Architecture

AI services should include:
- context builder,
- prompt/version registry,
- model adapter,
- structured output validator,
- recommendation service,
- explanation service,
- AI usage/cost tracker.

Never expose provider API credentials or platform access tokens to an LLM.

The AI layer is platform-independent (Decision D16):

```text
Data → Deterministic Analytics → AI Context → LLM Recommendation → Schema Validation → Business Rules
→ Policy Validation → Budget Validation → Risk Validation → Authorization → Action Engine → Provider
→ Execution → Verification → Audit Log
```

- Data boundary (A12): External Platforms → Provider Connectors → Normalized Data → Deterministic Calculations → Validated Business Context → AI Reasoning → Recommendation → validation chain → Authorization → Action Engine.
- AI context is built only from normalized AdVegaX data and deterministic analytics results, never from raw provider payloads.
- The LLM has no tools that touch databases, arbitrary APIs, advertising accounts, financial systems, billing, shell commands or code execution. It returns structured output only.

## 13. Financial Architecture

Financial service receives normalized commerce/ad data and calculates deterministic metrics.

Example:

```text
Commerce data + Ad spend + Product cost
             ↓
       Financial Engine
             ↓
Revenue / Spend / ROAS / CPA / Profit
```

Use consistent currency and time-period rules.

## 14. Analytics Architecture

Store raw/normalized events and daily/hourly aggregates.

Avoid recalculating expensive reports from raw provider data on every dashboard request.

## 15. Caching

Redis may be used for:
- short-lived caches,
- job queues,
- rate limiting,
- temporary OAuth state where appropriate.

Do not use cache as the authoritative source of financial or security data.

## 16. Observability

Production should provide:
- structured logs,
- metrics,
- error tracking,
- request tracing/correlation IDs,
- provider API latency/error metrics,
- job success/failure metrics,
- AI latency/cost metrics.

## 17. Deployment

Environments:
1. Local
2. Development
3. Staging
4. Production

Promotion:
```text
Feature branch
→ CI
→ Review
→ Development
→ Staging
→ Production
```

Production must not be the first environment where a change is tested.

Portability and configuration (Decisions D9, D13):
- The hosting provider and region are not yet selected. Everything runs as containers; no dependency on proprietary hosting features without a documented reason.
- Required capabilities: Docker, PostgreSQL, Redis, FastAPI, Next.js, Celery workers, scheduled jobs, HTTPS, secret management, logging, monitoring, backups, separate staging and production.
- Logical domains: `app.<primary-domain>` (web) and `api.<primary-domain>` (API). Domains, OAuth callback URLs and allowed origins come from environment configuration and differ per environment; nothing is hard-coded.
- CORS uses an explicit origin allowlist; `*` is never used for authenticated production requests.

## 18. Scaling Strategy

Initial scaling:
- horizontal FastAPI instances,
- separate workers,
- PostgreSQL optimization,
- Redis,
- indexed queries,
- aggregation tables.

Later:
- extract high-load domains into services only when measurable bottlenecks justify it.

## 19. Disaster Recovery

Plan for:
- automated database backups,
- restore testing,
- point-in-time recovery where supported,
- encrypted backups,
- documented recovery procedure,
- incident ownership.

## 20. Security Boundary

Critical boundaries:
- browser ↔ API,
- user ↔ organization,
- application ↔ provider,
- AI ↔ action engine,
- application ↔ database,
- staging ↔ production.

Every boundary requires explicit authentication/authorization/validation.

## 21. Design Principle

Optimize for correctness, auditability and maintainability before premature scale.
