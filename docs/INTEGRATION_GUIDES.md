# AdVegaX — Integration Guides

**Status:** Phase 1B framework in place; no real provider yet (first: Shopify, Phase 2A). · **Last updated:** 2026-10-08

This guide explains how a platform connector is added on top of the Phase 1B integration foundation. Each real provider still needs its own approved phase plan before code is written.

---

## 1. What already exists (Phase 1B)

| Piece | Location | Purpose |
|---|---|---|
| Provider protocol | `app/providers/base/interfaces.py` | `PlatformProvider`: authorization URL, complete authorization (PKCE), discover resources, sync resource, revoke |
| Category protocols | same file | `CommerceProvider`, `AdvertisingProvider`, `AnalyticsProvider` — empty until the first provider of each category defines its normalized methods |
| Types | `app/providers/base/types.py` | `ResourceDescriptor`, `ConnectResult`, `SyncSummary`, `Money` (Decimal + ISO currency) |
| Capabilities / availability | `app/providers/base/capabilities.py`, `availability.py` | Declare what the platform supports; missing data is `unavailable` / `unsupported` / `not_synchronized`, never 0 |
| Errors | `app/providers/base/errors.py` | Normalized errors; `retryable` drives job retry vs fail |
| Registry | `app/providers/base/registry.py` | Registers providers; refuses test-only providers in staging/production |
| Safe HTTP | `app/providers/http/client.py` | The **only** way to call a platform (SSRF protections, timeouts, size limits) |
| Rate limiter | `app/providers/http/ratelimit.py` | Redis token bucket per provider/key |
| Connections, credentials, links, jobs | `app/domains/integrations/`, `app/domains/jobs/` | Generic — no provider-specific code |
| Reference implementation | `app/providers/fake/provider.py` | Deterministic test provider |

## 2. Provider onboarding checklist

Before code:
- [ ] Phase plan approved (scopes, API version, rate limits, data mapped, review/approval requirements such as Shopify app review, Google Ads developer token, Meta App Review).
- [ ] Facts verified against the platform's official documentation (date and link recorded in the plan).
- [ ] Sandbox / test account available.
- [ ] Minimum scopes listed and justified (read-only first).

Implementation:
- [ ] New package `app/providers/<code>/` implementing `PlatformProvider` (+ category protocol methods).
- [ ] `code`, `category`, `auth_scheme`, `capabilities`, `rate_limit` declared; `test_only = False`.
- [ ] All HTTP calls through `SafeHttpClient` with an allowlisted host pattern and ports; no other HTTP library (ruff `TID251` enforces).
- [ ] PKCE and `state` used for OAuth; redirect URI built from `API_BASE_URL`.
- [ ] Platform errors mapped to `AuthExpiredError`, `PermissionDeniedError`, `RateLimitedError(retry_after)`, `RetryableError`, `InvalidRequestError`, `UnknownOutcomeError` — **codes only**, never raw platform messages that may echo tokens.
- [ ] Money as `Decimal` with currency; timestamps timezone-aware; external IDs stored as text.
- [ ] Missing values return `MetricValue.missing(...)` with the right availability state.
- [ ] `revoke` implemented where the platform supports token revocation (declare `TOKEN_REVOCATION`).
- [ ] Provider client secrets come from settings / secret store only; never committed.
- [ ] Registered in `build_registry`.

Tests (required before review):
- [ ] Recorded/mocked responses (no live calls in CI).
- [ ] Error mapping for 401, 403, 404, 429 (+ `Retry-After`), 5xx, timeouts.
- [ ] Tenant isolation: route sweep still passes; resources from organization A never visible to B.
- [ ] Credentials never appear in responses, logs or audit (extend `tests/security/test_credentials.py`).
- [ ] Capability/availability behaviour for unsupported data.
- [ ] Coverage gates (85 % overall, 95 % security-critical) still met.

Documentation:
- [ ] `API_SPECIFICATION.md`, `DATABASE_SCHEMA.md` (any resource-extension tables), `SECURITY.md` (scopes, data held), this guide (§3 entry), `PROJECT_STATUS.md`.

## 3. Provider entries

Add one section per provider when its phase is implemented.

### Template — `<Provider name>` (`<code>`)
- **Category / auth scheme:**
- **API version and docs verified on:**
- **Scopes:**
- **Resources discovered:** (kind, external ID, currency, timezone)
- **Capabilities:**
- **Rate limits:**
- **Data synchronized:**
- **Revocation:**
- **Known limitations:**

### Fake provider (`fake`) — test/local only
- **Category / auth scheme:** advertising / OAuth 2 with PKCE.
- **Resources:** two ad accounts (AUD, USD) and one store (NPR) by default; configurable.
- **Capabilities:** PKCE, token revocation.
- **Configurable failures:** auth expired, permission denied, rate limited N times, N transient failures, revoke failure.
- **Never available in staging/production** (registry refuses it).
