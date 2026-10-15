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

### Shopify (`shopify`) — Phase 2A, implemented against the simulator (live checks pending)
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
- **Keeping up to date (2A-07):** webhooks are "object X changed" signals — the current product (`product(id:)`, ≤ 250 variants) or order (`order(id:)`, ≤ 100 lines, ≤ 10 agreements × 50 sales) is fetched and upserted with the import's mapping; an object larger than that is applied as far as fetched and the store is reconciled by bulk export. `inventory_levels/update` refreshes the variant's product; `refunds/create` refetches its order (`order_id`); `products/delete` marks the product deleted (order history kept); `orders/delete` removes the order. Bursts for one object are coalesced (`COMMERCE_FETCH_COALESCE`). Hourly reconciliation: products and orders with `updated_at` since the last run minus `COMMERCE_RECONCILE_OVERLAP`; nightly deep check: whole catalogue + orders created in the last 30 days; "Sync now" runs the deep check. THROTTLED responses back off by `(requestedQueryCost − currentlyAvailable) / restoreRate` (1–60 s).
- **Privacy webhooks (2A-07):** `customers/data_request` / `customers/redact` → recorded as "no personal data held" (nothing about customers is stored) and the customer id is dropped from the intake log; `shop/redact` → every imported row for the store is deleted (skipped and audited if the store was connected again).
- **Testing without Shopify (2A-11):** `backend/tests/shopify_sim.py` answers the token endpoint, the GraphQL Admin API (bulk exports, single-object fetches, throttling) and the bulk download host in Shopify's documented formats, behind the real `SafeHttpClient`. It can also enforce rotation (`strict_tokens`: only the latest access token works; `uninstall()` invalidates all). `tests/api/test_shopify_journey.py` runs the whole lifecycle. The browser suite connects a simulated store with `tests/e2e_shopify_store.py`. CI never calls Shopify.
- **To confirm live (development store):** exact scope behaviour incl. whether `Order.customer.id` needs `read_customers`; bulk query shapes; app-initiated revocation; bulk-download host; `read_all_orders` and expiring tokens for custom-distribution apps; Sales-report reproduction (Step 0, plan §4.2); webhook headers on privacy topics (`X-Shopify-Webhook-Id`, `-Triggered-At`) as documented; bulk-export download host (`storage.googleapis.com` in the docs' examples); the orders search filter `created_at:>=` and `Order.updatedAt`; inline fragment `... on ProductSale { lineItem { id } }` inside a bulk query.

### WooCommerce (`woocommerce`) — Phase 2B, in progress
- **Category / auth scheme:** commerce / API keys created by the store's `/wc-auth/v1/authorize` page (scope `read`), delivered to AdVegaX by the store (server to server). HTTP Basic auth over HTTPS; keys never in URLs.
- **API:** REST `wc/v3` under `{store}/wp-json`; public WordPress index `/wp-json/` for the site name and time zone. Facts verified against WooCommerce docs on 2026-10-14 (`PHASE_02B_PLAN.md §4.1`).
- **Connect (2B-04):** `start` with `{"store_url"}` → address checked (public index, `wc/v3` namespace) → the store's `/wc-auth/v1/authorize?app_name=AdVegaX&scope=read&user_id=<single-use state>&return_url=<API callback>&callback_url=<API …/credentials>`. The store posts `{key_id, user_id, consumer_key, consumer_secret, key_permissions}`. AdVegaX accepts it only if:
  - the permissions are `read`;
  - the key works on the recorded store (`system_status`);
  - WooCommerce is ≥ `WOOCOMMERCE_MIN_VERSION` (9.0).

  The browser then returns to the API callback and sees the outcome. One live connection per store (host + lower-cased path); reconnect reuses the connection. Disconnect deletes AdVegaX's copy only (a read key cannot revoke itself). Offered only when `WOOCOMMERCE_ENABLED=true`.
- **Discovery:** one `store` resource with its name (WordPress), currency (`system_status.settings.currency`) and time zone. The time zone comes from WordPress `timezone_string`, or from a whole-hour `gmt_offset` mapped to `Etc/GMT±N`. A fractional offset leaves it empty, so the store cannot be imported until a named zone is set (to show on the store page in 2B-06).
- **Data synchronized (2B-05, paged import):**
  - **Catalogue:** products (all types, by id), then the variations of each variable product.
    - A simple product is its own single variant.
    - Statuses map as publish → active, draft/pending → draft, private → unlisted, trash → deleted.
    - Stock is read only when managed (`manage_stock`, or `parent` for variations); otherwise it is "not tracked".
    - Product cost comes from `cost_of_goods_sold.total_value`.
  - **Orders:** created in the last 13 months (`after`, `dates_are_gmt=true`), with lines, shipping and fee lines, and the order-time cost per line from `line_items[].cost_of_goods_sold.value` (taken as the line total ÷ quantity, to confirm live). A line without a recorded cost has **no cost**: it is never given a later product cost.
  - **Refunds:** from `/refunds`, with their lines linked to the original line through `_refunded_item_id`. Any refunded amount not covered by lines becomes an `adjustment` reversal.
  - **Customer details:** never read or stored. Requests also send `_fields` so the store need not send them.
  - **Uncounted orders** are kept with a reason: `excluded_reason = status` (pending, failed, cancelled, drafts, trash) or `other_currency`.
  - **Sales records** use the same definitions as Shopify's: amount including tax, tax, and discount = subtotal − total.
  - **Changes:** `modified_after` on products, variable products and orders, and refunds created since the last check.
  - **Pace:** 2 requests per second per store; when the limit is reached the import pauses and resumes.
- **Store address (2B-03):** HTTPS, public DNS name, port 443, optional sub-folder; normalized as described in SECURITY §9. Identity across organizations: host + lower-cased path.
- **Errors (2B-03):**
  - 401 with `woocommerce_rest_authentication_error` → `key_rejected` (Needs reconnecting);
  - any other 401 to an authenticated request → `auth_header_stripped` (the host removes the `Authorization` header; fix guide);
  - 403 → `permission_denied`;
  - 404 `rest_no_route` → `woocommerce_api_not_found`;
  - other 404 → `not_found`;
  - 429 → `rate_limited` (Retry-After honoured, at most 300 s);
  - 5xx → retried;
  - redirects → `store_redirected`;
  - non-JSON answers (e.g. security-plugin pages) → `unexpected_response`.
- **Paging:** `page` / `per_page` (≤ 100) with `X-WP-Total` / `X-WP-TotalPages`; history is read through the paged-import framework (2B-02).
- **To confirm live (Step 0, plan §4.2):** see the plan's list. It includes the error identifiers above, whether `_fields` stops customer details from being sent, the maximum `per_page`, and line-total tax treatment.

### Fake provider (`fake`) — test/local only
- **Category / auth scheme:** advertising / OAuth 2 with PKCE.
- **Resources:** two ad accounts (AUD, USD) and one store (NPR) by default; configurable.
- **Capabilities:** PKCE, token revocation.
- **Configurable failures:** auth expired, permission denied, rate limited N times, N transient failures, revoke failure.
- **Never available in staging/production** (registry refuses it).
