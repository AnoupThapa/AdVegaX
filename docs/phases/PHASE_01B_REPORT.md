# Phase 1B — Implementation Report

**Date:** 2026-10-08 · **Branch:** `feature/phase-1a` (1B commits on top of 1A) · **Status:** Implemented — awaiting product-owner review
**Plan:** `PHASE_01B_PLAN.md` (approved, A16) · Phase 1C and all real providers (Shopify, WooCommerce, Google Ads, Meta, GA4) were **not** started.

---

## 1. Summary

Through the API, using only the test (fake) platform, a user can: start a connection → approve → callback → resources discovered by a background job → explicitly link a resource → queue a sync job → unlink / relink with history kept → disconnect (revoked at the platform, credentials erased, links ended). Everything is tenant-isolated by RLS, credentials are encrypted, outbound calls go through the SSRF-safe client, and changes and refusals are audited.

Verified end to end with a real uvicorn server, a real Celery worker and Celery beat: register → login → create organization → start → callback (303 `connected`) → worker discovered 3 resources → link (201) → sync job `succeeded` → disconnect `revoked`. Logs contained no tokens, secrets or errors; beat dispatched the email sweep on schedule.

## 2. Files changed

76 files, +5,026 / −145 lines (against the approved-plan commit `990c2a0`).

| Area | Files |
|---|---|
| Migrations | `alembic/versions/0005_integrations.py`, `0006_job_runs.py` (new) |
| Encryption | `app/core/security/encryption.py` (new) |
| Provider framework | `app/providers/base/{availability,capabilities,errors,interfaces,pkce,registry,types}.py`, `app/providers/http/{policy,client,ratelimit}.py`, `app/providers/fake/provider.py` (new) |
| Integrations domain | `app/domains/integrations/{models,credentials,connect_state,schemas,service,jobs,rotation,router}.py` (new) |
| Jobs domain | `app/domains/jobs/{models,service}.py`, `app/workers/job_tasks.py` (new) |
| Denial audit | `app/domains/audit/denials.py` (new); `organizations/permissions.py`, `organizations/service.py`, `main.py` (modified) |
| Wiring / settings | `core/settings.py`, `runtime.py`, `api/deps.py`, `api/router.py`, `db/models.py`, `workers/celery_app.py`, `workers/email_tasks.py` |
| Dependencies / CI | `pyproject.toml` (+`cryptography` 50.0.2, `httpx` 0.28.1 runtime), `uv.lock`, `Makefile`, `.github/workflows/ci.yml` (security-critical coverage list extended), `.env.example` (new settings), `docker-compose.yml` (new `beat` scheduler service), `.gitleaks.toml` (new; allowlists only the public local-only dev key) |
| Tests (new) | `tests/security/test_ssrf.py`, `test_credentials.py`, `tests/api/test_connections.py`, `tests/workers/test_jobs.py`, `tests/unit/test_encryption.py`, `test_connect_state.py`, `tests/providers/test_base.py`, `test_ratelimit.py` |
| Tests (extended) | `conftest.py`, `helpers.py`, `security/test_rls.py`, `test_tenant_isolation.py`, `test_static_rules.py`, `api/test_audit.py`, `unit/test_settings.py` |
| Docs | `DATABASE_SCHEMA.md §4`, `API_SPECIFICATION.md §5`, `ARCHITECTURE.md §9`, `SECURITY.md §4–§10`, `INTEGRATION_GUIDES.md` (new), `MASTER_SPECIFICATION.md` (A16), `PROJECT_STATUS.md`, `ROADMAP.md`, `PHASE_01_FOUNDATION.md`, `PHASE_01B_PLAN.md`, this report, `README.md` |

**Deleted files: none** (A1).

## 3. Database migrations

| Migration | Contents |
|---|---|
| `0005_integrations` | `external_connections`, `external_connection_credentials`, `external_resources`, `organization_resource_links`; composite FKs on `(organization_id, id)`; partial unique index (one active link per resource); check constraints for status/kind/auth scheme/unlink reason and "secret columns all-or-nothing"; RLS enabled + forced; app role SELECT/INSERT/UPDATE (no DELETE); system role SELECT/UPDATE on credentials for key rotation only |
| `0006_job_runs` | `job_runs` with status, attempts, next attempt, error code, subject and correlation fields; RLS enabled + forced; app role tenant-scoped; system role SELECT/UPDATE to claim/retry/recover |

Both verified: upgrade → downgrade → upgrade on an empty database, no model/migration drift, RLS catalog and role-attribute checks.

## 4. Security controls

| Control | Where | Proven by |
|---|---|---|
| Organization-owned connections; authorizing user recorded | `integrations/service.py` | `test_connections_are_isolated_per_organization` |
| Credentials encrypted (envelope, AES-256-GCM, tenant-bound AAD) | `core/security/encryption.py`, `integrations/credentials.py` | `test_encryption.py`, `test_credentials.py` |
| Credentials never in responses, logs, audit, errors | schemas have no secret fields; log scrubber; codes-only errors | `test_secrets_are_encrypted_at_rest_and_never_exposed` |
| Decryption boundary | only `app/domains/integrations/` | `test_credential_boundary` (source rule) |
| SSRF-safe outbound client | `providers/http/` | `test_ssrf.py` (81 cases) |
| HTTP libraries banned elsewhere | ruff `TID251` + source test | `test_static_rules.py` |
| Connect state single-use, 10 min, bound to user/org/provider/PKCE | `connect_state.py` | `test_connect_state.py`, `test_state_is_single_use_and_bound_to_user_and_provider`, `test_expired_state` |
| Callback takes organization only from state; re-checks user + permission | `service.complete` | `test_callback_rejections`, `test_user_cancelled_and_permission_lost_mid_flow` |
| PKCE S256 | `providers/base/pkce.py` | `test_pkce_rfc7636_vector` |
| Per-provider rate limiting | `providers/http/ratelimit.py` | `test_ratelimit.py` |
| Test provider refused in staging/production | `registry.py` | `test_registry_rules` |
| Forced RLS + composite FKs on all 5 tables | migrations | `test_rls.py` |
| Refused actions audited | `audit/denials.py`, `main.py` handler | `test_refused_actions_are_audited`, `test_denial_audit_failure_is_contained` |
| Deployed environments refuse dev encryption keys / non-https `API_BASE_URL` | `settings.py` | `test_settings.py` |

## 5. Credential encryption design

- Per-record random 256-bit **data key**; secrets JSON encrypted with AES-256-GCM, random 96-bit nonce.
- Data key wrapped with AES-256-GCM by the active **key-encryption key** (`ENCRYPTION_KEYS`, versioned; `ENCRYPTION_ACTIVE_KEY_VERSION`), behind a `KeyProvider` interface — a cloud KMS can replace the local key ring later without changes elsewhere.
- **Associated data** `advegax:credential:v1|org|connection|provider`: ciphertext moved to another row or tenant fails to decrypt.
- **Stored:** ciphertext, wrapped data key, key version (+ provider, status, authorizing user, scopes, timestamps, external IDs on the connection). Nothing else.
- **Rotation:** add a key version, activate it, run `python -m app.domains.integrations.rotation` — data keys are re-wrapped; ciphertext untouched. Tested.
- **Disconnect:** provider revocation where supported (failure tolerated and recorded), then ciphertext, wrapped key and version are nulled.
- Missing/unreadable credentials surface as an **expired** connection, never as an error carrying secret material.

## 6. Connection / resource model

```text
Organization ──owns──▶ External Connection (authorized_by_user_id, status, scopes, encrypted credentials)
                          └── External Resources (discovered; accessible flag; capabilities)
                                 └── Organization Resource Links (explicit; one active; history kept)
```

- Status: `active` → `expired` (auth failure) / `error` (permission failure) / `revoked` (disconnect).
- Rediscovery marks vanished resources inaccessible and ends their links (`resource_inaccessible`).
- Disconnect ends links (`connection_revoked`). Unlink by a user → `user`. Relink creates a new row.
- Same platform account in two organizations = two independent connections (A16).

## 7. Test results by area

| Area | Tests | Highlights |
|---|---:|---|
| **Fake-platform flow** | 15 (`api/test_connections.py`) | Full journey with audit history; rediscovery; callback rejections (bad/reused/expired state, other user, other provider, cancelled, permission lost); view-vs-manage roles; unknown provider; auth expiry → `expired`; permission denied → `error`; disconnect when provider revoke fails; per-organization isolation |
| **SSRF** | 81 (`security/test_ssrf.py`) | Schemes (`http`, `file`, `gopher`, `ftp`, …); credentials in URL; localhost, 127.0.0.1, `::1`, private IPv4, link-local, 169.254.169.254, CGNAT, IPv6 ULA/link-local, IPv4-mapped/NAT64/6to4/Teredo; decimal/octal/hex/short IP encodings; internal hostnames; ports; mixed public+private DNS answers; **DNS rebinding** (pinned address); **redirects to private addresses** and other re-validated targets; cross-host and hop limits; credential headers stripped; oversized responses (declared and streamed); connect/read timeouts; proxy environment ignored; positive controls |
| **Background jobs** | 10 (`workers/test_jobs.py`) | Rate-limited → backoff → success; retryable → **dead-letter**; subject gone / unknown type → failed without retry; unexpected error → retried, code only; job cannot cross tenants; stuck-job recovery; **scheduler singleton lock**; scheduled tasks once per window; automatic email sweep; backoff cap + `Retry-After` |
| **Tenant isolation** | 4 route-level + 3 new RLS tests | Route sweep over **every** organization route (now ≥ 19, generated from OpenAPI) → 404 for non-members; foreign connection/resource/job IDs → 404; raw RLS on all five tables; composite FKs reject cross-tenant references; runtime role cannot DELETE |
| **Credentials** | 4 + 4 unit | At-rest encryption and no exposure; cross-tenant ciphertext fails; disconnect erases; key rotation |
| **Audit** | 2 new + journey assertions | Every journey action present in the audit log; `connection.health_changed` checked for actor (worker), resource, result and code-only payload; refused actions recorded as `authorization.denied`; audit failure contained |
| **Route guards** (follow-up) | 5 (`security/test_route_guards.py`) | Generated from OpenAPI for **every** route: signed-out callers get 401 on all 29 protected routes; every state-changing route refuses a missing or forged CSRF token (403) and changes nothing; every route with an ID in its path rejects a malformed ID (422) without echoing it; unknown providers refused |

## 8. Audit-log verification

Recorded actions: `connection.authorization_started`, `connection.created`, `connection.discovered`, `connection.health_changed`, `connection.revoked` (with `revoked_at_provider`, `links_ended`), `resource.linked`, `resource.unlinked`, `resource.sync_requested`, `resource.synced`, `authorization.denied`. Tests assert that every journey action is present (presence, not order), that `connection.health_changed` carries only status and error codes, and that the access and refresh tokens appear in no audit, security-event, job, connection or resource row, no API response and no log output.

## 9. Coverage, lint and type-check results

PostgreSQL 16, Redis 7, Python 3.12.

| Check | Result |
|---|---|
| `ruff check` + `ruff format --check` | ✅ pass |
| `mypy --strict` (90 source files) | ✅ no issues |
| Tests | ✅ **277 passed**, 0 failed (unit 67 · API 59 · security 125 · providers 7 · migrations 4 · workers 15) — 272 at first delivery; +5 in the verification follow-up (§13) |
| Coverage — overall | ✅ **98.40 %** (gate 85 %) |
| Coverage — security-critical (now incl. encryption, `providers/http`, credentials, connect state) | ✅ **99 %** (gate 95 %) |
| Migrations | ✅ up/down/up, no drift, RLS catalog, role checks |
| `pip-audit` | ✅ no known vulnerabilities |

## 10. Deviations from the approved plan

| # | Deviation | Reason / impact |
|---|---|---|
| 1 | Single scheduler is enforced by a Redis `SET NX EX` lock **per scheduled run**, not a lock on the beat process | Same outcome (one execution per window even with two beat processes), and survives a crashed beat without a stale process lock |
| 2 | No connect-state cleanup task | Redis TTL expires state automatically |
| 3 | Connection status `pending` not used | A connection row is created only after a successful callback; in-flight state lives in Redis |
| 4 | Added `external_resources.last_synced_at` and the link-history endpoint `GET …/resources/{id}/links`; added `rediscover` and `GET …/jobs/{job_id}` | Needed to show sync freshness, link history and job status |
| 5 | New setting `API_BASE_URL` (https required when deployed) | OAuth redirect URIs point at the API host |
| 6 | System role has SELECT/UPDATE on credentials | Key rotation only (re-wrapping); it never decrypts secrets |
| 7 | SSRF client connects directly and ignores proxy variables | Any egress proxy is designed with hosting (Q16) |
| 8 | Category protocols (`CommerceProvider` etc.) are empty; `refresh_credentials` / `health_check` not in the protocol yet | Defined with the first real provider (2A) so the abstraction is not guessed; health is derived from call outcomes |
| 9 | Fake provider categorized as advertising | Exercises multi-resource discovery |
| 10 | Key rotation is recorded in structured logs (count, version), not `audit_logs` | Operator/system action with no user; system role has no audit insert grant |
| 11 | No separate maximum-header-size setting | httpx/h11 built-in header limits apply |
| 12 | No "slow response" fake mode | Timeouts tested directly on the SSRF client |
| 13 | `TenantTask` base class implemented as `run_job` + handler registry | Same guarantees (tenant context, subject re-check, `job_runs` record, correlation ID) |
| 14 | Normalized type `ExternalRef` (plan §2, §9) not created | Resources carry `provider`, `kind` and `external_id` fields directly; a dedicated type is added with the first real provider if it is needed. *Missed in the first report; found in verification.* |
| 15 | Decryption boundary is the **integrations domain** (`app/domains/integrations/`), not "provider code only" (plan §6.2) | The domain decrypts just before calling a provider and passes secrets in memory; providers never touch the database. Enforced by `test_credential_boundary`. *Missed in the first report; found in verification.* |

## 11. Not verified in this environment

Docker image build, gitleaks and GitHub Actions — they run in CI after the branch is pushed. Specifically never executed here: the new `beat` service in `docker-compose.yml` and the `.gitleaks.toml` allowlist (check the first CI run).

## 12. Remaining risks

| Risk | Severity | Status / mitigation |
|---|---|---|
| Abstractions designed without a real platform | MEDIUM | Interfaces kept minimal; finalized in 2A/2B |
| Local key ring until hosting/KMS chosen (Q16) | MEDIUM | `KeyProvider` interface; deployed environments refuse dev keys; rotation tested |
| Egress proxy/network policy not yet designed | MEDIUM | Depends on hosting (Q16); client-side controls in place |
| Same account in two organizations (Q6) | LOW | Allowed as separate connections; product decision still open for 2A |
| Redis outage blocks connect flow and rate limiting | LOW | Fails closed (503 / retryable); documented |
| Docker/CI not yet run | LOW | Runs on first push |

## 13. Verification follow-up (2026-10-08)

A final re-check before product-owner review found claims that were stronger than the evidence. Corrected:

| Finding | Correction |
|---|---|
| Plan §14 required unauthenticated, CSRF and invalid-input tests for every new endpoint; only wrong-tenant, wrong-role and not-found were tested | Added `tests/security/test_route_guards.py` (OpenAPI-generated, covers all current and future routes) |
| `connection.health_changed` audit listed as verified but not asserted | Added assertions to the auth-expired and permission-denied tests |
| "Full sequence" wording for the audit journey test | Reworded: the test checks presence, not order |
| `ExternalRef` and the decryption-boundary difference were not reported | Added as deviations 14 and 15 |
| Docker `beat` service and gitleaks allowlist not individually flagged as unverified | Added to §11 |

No application code changed in the follow-up; only tests and this report.

