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

### Shopify (`shopify`) — Phase 2A, in progress
- **Category / auth scheme:** commerce / OAuth 2 authorization-code grant (standalone app), **expiring offline tokens** (`expiring=1`: access 1 h, refresh 90 days, rotated on refresh). No PKCE (Shopify does not use it).
- **API version and docs verified on:** GraphQL Admin API `2026-10`; facts verified against shopify.dev on **2026-10-13** (`PHASE_02A_PLAN.md §4.1`). Live development-store checks deferred (option C, A18) — see "To confirm live".
- **Scopes:** `read_products`, `read_inventory`, `read_orders` (read-only); `read_all_orders` to be requested for 13-month history (Q9). A granted `write_x` satisfies `read_x`. Fewer scopes than required → `missing_scopes`.
- **Configuration:** `SHOPIFY_APPS` JSON list of `{client_id, client_secret, shops}` — several apps because custom distribution serves one merchant per app; `shops: ["*"]` for a development/public app. Shopify is offered only when at least one app is configured.
- **Connect:** start with the store address (`shop_domain`) or from a Shopify install link (`GET /connections/shopify/install`, HMAC + 5-minute freshness). Callback: HMAC with the serving app's secret, `shop` must equal the shop in the server-side state, then the token exchange. **One live connection per store across organizations**, checked before the exchange. Reconnect reuses the connection.
- **Resources discovered:** exactly one `store` (`shop.id` GID, name, currency, IANA time zone); the token must answer for the same `myshopifyDomain`.
- **Capabilities:** app install, webhooks, product cost, inventory, refund lines, presentment currency. **No token revocation** declared (no documented app-initiated revoke for this flow).
- **Rate limits:** cost-based (100/200/1,000 points per second by plan); `THROTTLED` and 429 → `rate_limited`. Cost-aware limiting in 2A-07.
- **Errors:** 401 → `auth_expired`; 402/403/423/`ACCESS_DENIED` → `permission_denied`; 404 → `not_found`; 429/`THROTTLED` → `rate_limited`; 5xx/invalid JSON → retryable. Response bodies and Shopify messages never enter errors or logs.
- **Token lifecycle (2A-04):** refresh with `grant_type=refresh_token`; the new refresh token replaces the old one (the old one is retired); any 4xx on refresh → `auth_expired` ("Needs reconnecting"), 5xx → retried. Refresh and reconnect share one account lock.
- **Webhooks (2A-05):** one endpoint, `POST {API_BASE_URL}/api/v1/webhooks/shopify`, for every topic. Verified: base64 HMAC-SHA256 of the raw body with the serving app's client secret (store-specific app first, then a `*` app); headers `X-Shopify-Topic`, `-Shop-Domain`, `-Webhook-Id` (de-duplication key), `-Triggered-At` (replay window). Topics handled: `app/uninstalled` (connection revoked at once, data kept), `customers/data_request`, `customers/redact`, `shop/redact` (recorded + audited; carried out in 2A-07), and the "object changed" topics `products/*`, `inventory_levels/update`, `orders/*`, `refunds/create`, `shop/update`, `bulk_operations/finish` (fetched by id in 2A-07). Subscriptions and the three privacy topics are declared in the app's configuration in the Dev Dashboard (set up with 2A-01).
- **Data synchronized (2A-06, initial import):** linking the store starts it. Bulk exports (`bulkOperationRunQuery`, polled with `bulkOperation(id:)`, JSONL streamed from the allowlisted storage host): products → variants (price, SKU, inventory quantity when tracked, unit cost from `InventoryItem.unitCost`); orders created since `history_from` (60 days, or 13 months with `read_all_orders`) → line items, sales agreements → sales (each with its own date, reason, action and line type), refunds. Amounts in the shop currency. Test orders excluded. Costs are an **import-time snapshot** (Shopify keeps no cost history), so imported order lines are marked `import_time`. No customer, email or address field is requested; the hashed customer key and order country stay empty until the scope check on a development store (Step 0 item 1).
- **To confirm live (development store):** exact scope behaviour incl. whether `Order.customer.id` needs `read_customers`; bulk query shapes; app-initiated revocation; bulk-download host; `read_all_orders` and expiring tokens for custom-distribution apps; Sales-report reproduction (Step 0, plan §4.2); webhook headers on privacy topics (`X-Shopify-Webhook-Id`, `-Triggered-At`) as documented; bulk-export download host (`storage.googleapis.com` in the docs' examples); the orders search filter `created_at:>=` and `Order.updatedAt`; inline fragment `... on ProductSale { lineItem { id } }` inside a bulk query.

### Fake provider (`fake`) — test/local only
- **Category / auth scheme:** advertising / OAuth 2 with PKCE.
- **Resources:** two ad accounts (AUD, USD) and one store (NPR) by default; configurable.
- **Capabilities:** PKCE, token revocation.
- **Configurable failures:** auth expired, permission denied, rate limited N times, N transient failures, revoke failure.
- **Never available in staging/production** (registry refuses it).
