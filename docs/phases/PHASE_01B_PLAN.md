# Phase 1B — Integration Foundation: Implementation Plan

**Status:** ✅ Approved by the product owner (2026-10-08, A16) — implementation authorized for Phase 1B only · **Implemented:** 2026-10-08 (`PHASE_01B_REPORT.md`) · **Date:** 2026-10-08
**Depends on:** Phase 1A (implemented; awaiting review) · **Followed by:** Phase 1C (frontend shell), then Phase 2A (Shopify)
**Governing documents:** MASTER_SPECIFICATION §20–§21 (D4, D12, D15, D19, A4, A6, A7, A10, A11), ARCHITECTURE §6, §9, §10, DATABASE_SCHEMA §4, §19, API_SPECIFICATION §5, SECURITY.md

> Approved 2026-10-08 with all §20 defaults (A16). Connection ownership = organization; authorization actor = user. Real providers remain out of scope.

---

## 1. Objective

Build everything a real platform integration will need, **without connecting to any real platform**:

- the approved **connection → external resources → organization resource links** model (A6), with explicit discovery and linking;
- **encrypted credential storage** behind a vendor-neutral key-management interface (D15);
- the **provider framework**: category interfaces, capability declarations, data-availability states, normalized base types, error taxonomy and registry (D4, A10);
- the **SSRF-safe outbound HTTP client** and a per-provider rate limiter (A11);
- a durable **background-job framework** with tenant context, retries, dead-lettering and a single-instance scheduler;
- a **fake provider**, used only in tests and local development, that exercises the whole flow end to end.

At the end of 1B a user can, through the API and using the fake provider: start a connection → complete the callback → see discovered resources → explicitly link one to the organization → queue a sync job → unlink and relink with history kept → disconnect — all tenant-isolated, audited and encrypted.

## 2. Scope

| Area | In scope |
|---|---|
| Connections & resources | `external_connections`, `external_connection_credentials`, `external_resources`, `organization_resource_links` with RLS; connect/callback/discover/link/unlink/disconnect services and API (API §5) |
| Credential encryption | Envelope encryption (AES-256-GCM), key provider interface, local key-ring provider for development/CI, ciphertext bound to tenant + connection, key rotation command |
| Provider framework | `CommerceProvider`, `AdvertisingProvider`, `AnalyticsProvider` interfaces (method signatures only where Phase 2+ will fill them), `ProviderCapabilities`, `Availability` (available, unavailable, unsupported, not_synchronized), normalized base types (`Money`, `ExternalRef`, `MetricValue`), error taxonomy, registry |
| SSRF-safe client | `providers/http/`: HTTPS-only, DNS resolution with address checks and pinning, redirect re-validation, timeouts, response-size cap, credential-safe redirects |
| Rate limiting | Redis token bucket keyed by provider + connection/resource |
| Job framework | `job_runs` table, tenant-aware Celery task base, retry with exponential backoff and jitter, dead-letter state, correlation-ID propagation, Celery beat with a single-instance lock |
| Scheduled jobs | Email-outbox sweep (closes the 1A gap); expired connect-state cleanup |
| 1A follow-up | Authorization denials written to `audit_logs` in a separate transaction (1A deviation 7) |
| Fake provider | `providers/fake/` — test/local only; refused by the registry in staging/production |
| Documentation | DATABASE_SCHEMA §4 final columns, API_SPECIFICATION §5 reference, SECURITY.md (encryption, SSRF, jobs), INTEGRATION_GUIDES.md skeleton (provider-onboarding checklist) |

## 3. Non-goals

- Any real provider (Shopify, WooCommerce, Google Ads, Meta, GA4) — Phases 2A–5.
- Webhook ingestion endpoints and the `webhook_events` table — introduced with Shopify (2A).
- `sync_runs` with cursors and data tables (products, orders, campaigns, …) — Phase 2A+.
- `idempotency_keys` — introduced with the Action Engine (10A), as recorded in DATABASE_SCHEMA §0.
- Cloud KMS adapters — after the hosting decision (Q16).
- Frontend (Phase 1C) and resource-level user permissions (A7).

## 4. Dependencies

### 4.1 New runtime packages **[Decision]**

| Package | Why | Alternative |
|---|---|---|
| `cryptography` | AES-256-GCM envelope encryption (audited, standard library choice for Python) | None reasonable — do not hand-roll cryptography |
| `httpx` (move from dev to runtime) | Foundation of the SSRF-safe client; supports pinning a validated IP while keeping TLS SNI/hostname verification | `urllib3` (lower level, more custom code) |

No other new dependencies. Celery beat is part of Celery (already approved).

### 4.2 Prerequisites
- Phase 1A accepted by the product owner.
- No platform credentials needed (fake provider only).

## 5. Proposed files and directories

```text
backend/app/
├── core/security/encryption.py          envelope encryption, KeyProvider interface, LocalKeyRing
├── domains/integrations/
│   ├── models.py                        connections, credentials, resources, links
│   ├── schemas.py  router.py  service.py  permissions (extends matrix)
│   ├── connect_state.py                 single-use connect state (Redis, GETDEL)
│   └── credentials.py                   encrypt/decrypt boundary (providers only)
├── providers/
│   ├── base/                            interfaces.py capabilities.py availability.py types.py errors.py registry.py
│   ├── http/                            client.py (SSRF-safe) resolver.py ratelimit.py
│   └── fake/                            provider.py (test/local only)
├── domains/audit/denials.py             separate-transaction denial auditing
└── workers/
    ├── base.py                          TenantTask (org context, job_runs, retries, DLQ)
    ├── schedule.py                      beat schedule + single-instance lock
    └── maintenance_tasks.py             outbox sweep, connect-state cleanup
backend/alembic/versions/0005_integrations.py  0006_job_runs.py
backend/tests/{providers,integrations,security/test_ssrf.py,workers/test_jobs.py,...}
docs/INTEGRATION_GUIDES.md (new, skeleton)
```

## 6. Database tables (Phase 1B only)

All tenant-owned, RLS **enabled and forced**, `organization_id` on every table with composite foreign keys `(organization_id, parent_id)` so cross-tenant references are impossible.

### 6.1 `external_connections`
| Column | Notes |
|---|---|
| id, organization_id | PK; tenant |
| provider | registry code (e.g. `fake`; later `shopify`, `google_ads`) |
| auth_scheme | `oauth2`, `api_key`, `app_key` (WooCommerce-style) |
| authorized_by_user_id | FK users (who granted the authorization) |
| status | `pending`, `active`, `expired`, `revoked`, `error` |
| granted_scopes | text[] as returned by the provider |
| external_account_label | non-secret display label (e.g. shop domain) |
| last_error_code, last_error_at | provider error taxonomy code only — no raw payloads |
| created_at, updated_at, revoked_at | |

### 6.2 `external_connection_credentials`
| Column | Notes |
|---|---|
| connection_id (PK), organization_id | 1:1 with connection |
| ciphertext | AES-256-GCM of the JSON secret bundle (access/refresh token or key/secret) |
| wrapped_data_key | per-record data key wrapped by the key provider |
| key_version | key-ring version used to wrap |
| token_expires_at, refresh_expires_at, last_refreshed_at | non-secret lifecycle metadata |
| created_at, updated_at | |

Associated data for encryption = `organization_id | connection_id | provider`: a ciphertext copied to another row or tenant fails to decrypt. Grants: the API role may INSERT/UPDATE (connect flow) and SELECT within its tenant; decryption happens only in `domains/integrations/credentials.py`, which only provider code may call (source-rule test). Credentials never appear in API responses, logs, audit payloads or AI context (tests).

### 6.3 `external_resources`
| Column | Notes |
|---|---|
| id, organization_id, connection_id | |
| kind | `store`, `ad_account`, `analytics_property`, `business_asset` |
| provider, external_id (text) | unique `(connection_id, kind, external_id)` |
| display_name, currency, timezone | as reported; nullable |
| accessible | false when a rediscovery no longer returns it |
| capabilities | jsonb snapshot of the provider's declared capabilities for this resource |
| discovered_at, last_seen_at | |

### 6.4 `organization_resource_links`
| Column | Notes |
|---|---|
| id, organization_id, external_resource_id | |
| status | `active`, `unlinked` |
| linked_by_user_id, linked_at | |
| unlinked_by_user_id, unlinked_at, unlink_reason | `user`, `connection_revoked`, `resource_inaccessible` |

Partial unique index: one **active** link per resource. Unlink + relink creates a new row (history kept, A6).

### 6.5 `job_runs`
| Column | Notes |
|---|---|
| id, organization_id (nullable for system jobs) | |
| job_type, status | `queued`, `running`, `succeeded`, `failed`, `dead` |
| subject_type, subject_id | e.g. `external_resource` + id |
| attempts, max_attempts, next_attempt_at, last_error_code | |
| correlation_id, requested_by_user_id | |
| created_at, started_at, finished_at | |

RLS: tenant rows visible within the tenant; system rows only to `advegax_system`.

### 6.6 Migrations
`0005_integrations` (four tables, RLS, grants), `0006_job_runs` (table, RLS, grants). Both reversible and verified by the existing migration tests (up/down/up, drift, RLS catalog, role checks), which cover the new tables automatically.

## 7. API endpoints (API_SPECIFICATION §5)

| Endpoint | Permission | Notes |
|---|---|---|
| `GET /organizations/{id}/connections` | any member | status/health only; never secrets |
| `POST /organizations/{id}/connections/{provider}/start` | connections.manage | returns the redirect URL; state is single-use, 10-minute TTL **[Decision]**, bound to user + organization + provider (+ PKCE verifier where the provider supports it) |
| `GET /connections/{provider}/callback` | session + state | organization taken **only** from validated state; on success → discovery job queued; redirects to the app's Connections page |
| `GET /organizations/{id}/connections/{connection_id}` | any member | |
| `POST /organizations/{id}/connections/{connection_id}/disconnect` | connections.manage | revokes at the provider where supported; ends active links with reason `connection_revoked`; credentials deleted (ciphertext removed, row kept as tombstone) |
| `POST /organizations/{id}/connections/{connection_id}/rediscover` | connections.manage | queues discovery; marks missing resources `accessible=false` |
| `GET /organizations/{id}/connections/{connection_id}/resources` | any member | discovered resources with link status |
| `POST /organizations/{id}/resources/{resource_id}/link` | connections.manage | explicit; audited |
| `POST /organizations/{id}/resources/{resource_id}/unlink` | connections.manage | history kept; audited |
| `POST /organizations/{id}/resources/{resource_id}/sync` | connections.manage | linked resources only; queues a job (fake provider in 1B) |
| `GET /organizations/{id}/jobs/{job_id}` | any member | job status (no internal error detail) |

`connections.manage` = Owner, Admin, Manager (API §24). The tenant-isolation route sweep picks up every new organization route automatically.

## 8. Credential encryption design

- **Envelope encryption:** each credential record gets a fresh 256-bit data key; the secret bundle is encrypted with AES-256-GCM (random 96-bit nonce, associated data per §6.2); the data key is wrapped by the **key provider**.
- **Key provider interface:** `wrap(data_key) -> (wrapped, version)` / `unwrap(wrapped, version)`. Phase 1B ships `LocalKeyRing`, configured from `ENCRYPTION_KEYS` (versioned, base64, from the secret store) and `ENCRYPTION_ACTIVE_KEY_VERSION`. Cloud KMS adapters are added once hosting is chosen; no code outside the adapter changes.
- **Rotation:** new active version for new writes; a management command re-wraps existing data keys; old versions are removable after re-wrap.
- **Startup safety:** staging/production refuse to start with missing, short or development keys.
- Secrets are decrypted only for the duration of a provider call and never logged (scrubber + tests).

## 9. Provider framework

```text
providers/base/
  interfaces.py    CommerceProvider / AdvertisingProvider / AnalyticsProvider (Protocols)
                   shared: start_connect, complete_connect, refresh_credentials, revoke,
                           health_check, discover_resources
                   category read methods declared, implemented from Phase 2A
  capabilities.py  ProviderCapabilities (webhooks, product_cost, inventory, refund_lines,
                   presentment_currency, validate_only, create_campaign, ecommerce_events, …)
  availability.py  Availability enum + MetricValue(value | None, availability, source, as_of)
  types.py         Money (Decimal + ISO currency), ExternalRef, ResourceDescriptor
  errors.py        Retryable, RateLimited(retry_after), AuthExpired, PermissionDenied,
                   NotFound, InvalidRequest, UnknownOutcome
  registry.py      provider_code → implementation + capabilities; refuses test-only providers
                   when deployed
```

Rules enforced by tests: core domains import only `providers.base`; provider modules are the only code importing `providers.http`; `MetricValue` with non-available state always has `value=None` (A10).

## 10. SSRF / network security (A11)

Implemented in `providers/http/` and used by every future provider:

| Control | Design |
|---|---|
| Protocols | `https` only; no credentials in URLs; ports 443 by default (allowlist per provider if needed) |
| Hostname | IDNA-normalized; IP literals, single-label and internal names (`localhost`, `*.local`, `*.internal`, metadata hostnames) rejected |
| DNS | Resolved by the client; **every** returned address checked; connection made to a validated address with TLS SNI and certificate verification against the original hostname (prevents DNS rebinding) |
| Blocked ranges | loopback, private (RFC 1918), link-local (incl. 169.254.169.254), CGNAT 100.64/10, multicast, reserved/unspecified, broadcast, IPv6 ULA/link-local/loopback, IPv4-mapped/-compatible IPv6, 6to4/Teredo embeddings, and other non-global addresses |
| Redirects | Not followed automatically; each target re-validated; cross-host redirects refused by default; max 3 hops; credentials never forwarded |
| Limits | connect/read/total timeouts; maximum response size (streamed, aborted when exceeded); maximum header size |
| Logging | host and status only; never query strings, headers or bodies with credentials |

Test suite: localhost and every blocked range (IPv4 and IPv6 forms, decimal/octal/hex IP encodings), DNS rebinding (resolver returns public then private), redirect to private address, cross-host redirect, oversized response, slow response timeout, `http://` and `file://` schemes, credentials-in-URL, and a positive control.

## 11. Job framework

- **`TenantTask`** base class: tasks receive `organization_id` + subject IDs only; each run opens its own unit of work with tenant context, re-checks that the subject belongs to that organization, records a `job_runs` row, and propagates the correlation ID.
- **Retries:** exponential backoff with jitter for `Retryable`/`RateLimited` (respecting `retry_after`); `AuthExpired`/`PermissionDenied` mark the connection's health and stop; exhausted retries → `dead` (dead-letter) with error code, never raw payloads.
- **Durability:** `job_runs` is the source of truth; `acks_late` + idempotent task bodies; a sweep re-queues jobs stuck in `queued`.
- **Scheduler:** Celery beat with a Redis lock so only one active scheduler runs even if two are deployed; schedules for outbox sweep, connect-state cleanup and stuck-job recovery. Schedule intervals are settings.

## 12. Fake provider

Implements the shared provider contract with deterministic, configurable behaviour (success, auth failure, rate limit, resource disappears, slow response) so connection, discovery, linking, sync-queuing, error-taxonomy and job-retry paths are tested without any network. Registered only when `ENVIRONMENT` is `local` or `test`.

## 13. Security controls (additions to SECURITY.md)

- Connect state: random, single-use (Redis `GETDEL`), short TTL, bound to user + organization + provider; callback rejects mismatched session user.
- Callback organization comes only from the state, never from query parameters (D11).
- Credential grants and decryption boundary (§6.2, §8); source-rule tests for the boundary.
- Audit: connection created/revoked, resource linked/unlinked, sync requested, credential rotation; authorization denials now audited (separate transaction).
- No secrets or provider payloads in logs, audit records, job errors or API responses.

## 14. Testing strategy

Same standards as 1A (real PostgreSQL 16 + Redis 7, coverage ≥ 85 % overall, ≥ 95 % security-critical). Security-critical scope extends to `core/security/encryption.py`, `providers/http/`, `domains/integrations/credentials.py` and `connect_state.py`.

| Suite | Examples |
|---|---|
| Unit | encryption round-trip, tamper/AAD/rotation failures; availability invariants; registry rules; error taxonomy mapping; rate limiter |
| SSRF | §10 list |
| API | every new endpoint: valid, invalid, unauthenticated, CSRF, wrong tenant (404), insufficient role (403), not found |
| Tenant isolation | route sweep (automatic), raw RLS tests for the five new tables, composite-FK rejection of cross-tenant references, ciphertext moved to another tenant fails to decrypt |
| Integration | full fake-provider flow: start → callback → discovery → link → sync job → unlink → relink (history) → disconnect |
| Jobs | retry/backoff, dead-letter, tenant re-check, stuck-job recovery, scheduler lock |
| Migrations | existing up/down/up, drift, RLS catalog and role checks (automatically include new tables) |

## 15. CI

No new jobs. Coverage gate include-list extended (§14). The Docker build and gitleaks run once the GitHub remote is reachable.

## 16. Documentation changes

DATABASE_SCHEMA §4 (final columns), API_SPECIFICATION §5 (reference + error codes), ARCHITECTURE §9–§10 (as-built notes), SECURITY.md (encryption, SSRF, jobs), new `docs/INTEGRATION_GUIDES.md` (provider-onboarding checklist and template; justified by D2 and A11), PROJECT_STATUS, phase files, `PHASE_01B_REPORT.md`.

## 17. Acceptance criteria

1. The full fake-provider journey in §1 works through the API.
2. Credentials are encrypted at rest; tests prove tamper, wrong-key and cross-tenant decryption fail; no credential appears in any response, log or audit record.
3. The SSRF suite passes, including DNS rebinding and redirect cases.
4. New tables have forced RLS and pass the isolation suites; the route sweep covers all new organization routes.
5. Jobs retry, dead-letter and recover as specified; only one scheduler is active.
6. Email outbox is swept automatically; authorization denials are audited.
7. Lint, format, `mypy --strict`, tests and coverage gates pass; migrations verified.
8. Documentation updated; implementation report lists changes, deviations, deleted files (A1) and limitations.

## 18. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| SSRF bypass via DNS rebinding or alternate IP encodings | CRITICAL | Resolve-then-pin with per-address checks; exhaustive encoding tests |
| Credential exposure (logs, responses, wrong tenant) | CRITICAL | Envelope encryption with tenant-bound AAD; boundary + scrubber tests |
| Abstraction designed without a real provider | MEDIUM | Keep interfaces minimal; category methods finalized in 2A/2B with two commerce providers |
| Job duplication or loss | MEDIUM | `job_runs` source of truth, idempotent tasks, stuck-job sweep, scheduler lock |
| Key management before hosting choice | MEDIUM | Local key ring behind an interface; cloud KMS adapter later without code changes elsewhere |

## 19. Rollback considerations

Feature branch + pull request; migrations `0005`/`0006` have tested downgrades; no production data exists; no external systems are contacted (fake provider only). Disabling the registry entry removes the flows without schema changes.

## 20. Decisions requested with approval

| # | Item | Recommendation |
|---|---|---|
| 1 | New dependencies `cryptography` and `httpx` (runtime) | Approve |
| 2 | **Connection ownership.** The approved model reads User → External Connection → Resources → Organization Links. This plan creates each connection **inside an organization** (tenant-owned, recording which user authorized it), rather than as a user-level object shared across organizations. | Approve — keeps credentials inside one tenant's RLS boundary. Using the same external account in another organization (e.g. an agency) means a separate connection there; Q6 decides whether that is allowed. |
| 3 | Connect-state lifetime | 10 minutes (setting `CONNECT_STATE_TTL`) |
| 4 | Disconnect behaviour | Revoke at provider where supported, end links, delete ciphertext, keep audit tombstone |
| 5 | Who may view connections and resources | All members; manage = Owner, Admin, Manager |
| 6 | Scheduler | Celery beat + Redis single-instance lock |
| 7 | New document | `docs/INTEGRATION_GUIDES.md` |
| 8 | Include the 1A follow-up (audited authorization denials) in 1B | Approve |
