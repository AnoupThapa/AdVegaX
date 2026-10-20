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

### WooCommerce (`woocommerce`) — Phase 2B, implemented against the simulator (live Step 0 pending)
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
- **Keeping up to date (2B-06):**
  - **Change checks:** the scheduler looks every 5 minutes (`SCHEDULE_COMMERCE_RECONCILE_TICK`), and each store is checked at its platform's interval — WooCommerce every `WOOCOMMERCE_RECONCILE_INTERVAL` (15 minutes), Shopify hourly as before.
  - **Nightly full check / "Sync now":** reads the whole catalogue. Products and variations it does not list are marked deleted (`COMPLETE_CATALOGUE`); order history is kept, and an empty answer deletes nothing.
  - **Daily health check** (first import and nightly check) records `platform_version` and `site_url`, plus one plain warning: `woocommerce_too_old`, `timezone_unknown` or `cost_of_goods_off` (cost of goods is detected as off when products carry no `cost_of_goods_sold` field). A failed check never fails the sync.
  - **Access problems** use the connection's existing health: a refused key → "Needs reconnecting"; a stripped header → error with `auth_header_stripped`.
  - **A store whose time zone was unknown** starts importing after a rediscovery finds a named zone.
  - **Counted order statuses** (processing, on-hold, completed, refunded; custom statuses count too) are shown on the store.
- **Figures (2B-07):** the same `finance-v1` definitions as Shopify; the Shopify and WooCommerce sample stores give identical daily figures to the cent. Only counted orders contribute (`excluded_reason` IS NULL). A status change on an older order rebuilds its order day at the next check. Orders in another currency are never summed: their placement and refund days are "not available — orders in other currencies" (`financial_daily.other_currency_orders`), and so are the totals of a period containing one.
- **Web app (2B-08):**
  - the connect form takes the store address (HTTPS only, sub-folder allowed) and explains a refused address before anything is sent;
  - every connect and sync code has a plain message;
  - the store page shows a health panel with the fix, the address, the WooCommerce version and the counted statuses;
  - the products page explains missing costs when cost of goods is off;
  - the disconnect dialog asks the merchant to revoke the key in WordPress.
- **Tests (2B-09):** `tests/woocommerce_sim.py` (simulator); `test_woocommerce_journey.py` (connect → import → 15-minute changes → refund → paid order → key revoked → reconnect → health → disconnect, with key, secret and customer-detail scans); browser test `e2e/woocommerce.spec.ts` through the helper `tests/e2e_woocommerce_store.py` (refuses deployed environments). CI switches WooCommerce on for the browser job only to show the form; no usable address is ever submitted, so no real store is called.
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

### Google Ads (`google_ads`) — Phase 3, implemented against the simulator (live Step 0 pending)
- **Category / auth scheme:** advertising / OAuth 2.0 web-server flow with **PKCE (S256)** and **offline access** (refresh token). Scopes: `https://www.googleapis.com/auth/adwords` and `openid`. `openid` is used only for the stable Google account id (`sub`) in the ID token, so a reconnect by the same person reuses the connection; no email, name or picture is requested or stored. The `adwords` scope covers read and write, so read-only is enforced in code (static guard: only `customers:listAccessibleCustomers`, `googleAds:search`, `googleAds:searchStream`).
- **Configuration:** offered only when `GOOGLE_ADS_ENABLED=true` **and** `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET` and `GOOGLE_ADS_DEVELOPER_TOKEN` are set (secret store / local untracked settings only). The API version is `GOOGLE_ADS_API_VERSION` (`v25`, Q-3-1).
- **Hosts:** browser → `accounts.google.com/o/oauth2/v2/auth`. Server → `oauth2.googleapis.com/token`, `oauth2.googleapis.com/revoke`, `googleads.googleapis.com/{version}`. All go through the SSRF-safe client; redirects are not followed.
- **Connect (3-03):** `start` takes no parameters and returns Google's consent address with `access_type=offline`, `prompt=consent`, `include_granted_scopes=false`, single-use state and a PKCE challenge.
  - Callback checks: the `adwords` scope was granted (a person can untick it); the code is exchanged with the verifier; the ID token's issuer, audience and expiry are checked (claims read without a signature check, because the token comes straight from Google's token endpoint over TLS).
  - Connection identity is `"{organization}:{sub}"`: a reconnect within the organization reuses the connection, and another organization can connect the same Google account (Q-3-11).
- **Tokens:** the access token lasts about 1 hour and is refreshed before expiry under the per-connection lock. A new refresh token from Google is saved; otherwise the old one is kept. `invalid_grant` → `google_sign_in_rejected` → "Needs reconnecting". Disconnect revokes the refresh token at Google (`/revoke`; a 400 means it is already invalid) and always deletes our copy.
- **Discovery (3-04):**
  - `customers:listAccessibleCustomers` returns direct access only. Each account it returns is read with `customer_client … WHERE customer_client.level <= 1` (itself plus its direct children), with itself as `login-customer-id`.
  - Each manager found is read the same way, with the **top** manager as `login-customer-id`, breadth first. Each manager is read once (loops are safe), with limits of 500 direct accounts, 200 managers and 5,000 accounts.
  - **Advertiser accounts only** become `ad_account` resources (Q-3-3). Each has its name, currency, time zone (validated IANA name), `group_path` (the managers above it, e.g. "Agency > Retail clients") and `access_hint` (the top manager to sign in through; not exposed by the API).
  - A directly accessible account is listed once, without a path.
  - Not linkable (`unavailable_reason`):
    - `account_not_enabled` (status not `ENABLED`, or the account refuses queries);
    - `developer_token_not_approved` (a real account with a Test-access token);
    - `no_account_access`;
    - `account_details_missing` (no currency or a time zone Python does not know).
  - A manager that cannot be read hides only its own accounts. A person with no Google Ads account finds none (the connection stays active). Rediscovery updates reasons and paths and keeps existing links.
- **Structure import (3-05):** linking an advertiser account creates its `ad_accounts` row and starts the import chain (`advertising.import_step`, one step per job, per-account lock).
  - Five operations: `customer` (name, currency, time zone, status), `campaign_budget`, `campaign`, `ad_group` and `ad_group_ad`, all through `searchStream` and through the account's manager when it has one.
  - **Budgets:** `period` `DAILY` / `FIXED_DAILY` → daily `amount_micros`; `CUSTOM_PERIOD` → lifetime `total_amount_micros`; micros ÷ 1,000,000 → exact decimal in the account currency. No amount → empty, never 0.
  - **Campaigns:** `advertising_channel_type` and `bidding_strategy_type` are kept as shown values. The dates are `start_date_time` / `end_date_time` (since v23; `"yyyy-MM-dd HH:mm:ss"` in the account time zone); no end date means it runs indefinitely.
  - **Statuses** `ENABLED` / `PAUSED` / `REMOVED` → active / paused / removed. Removed items are imported and kept; an unknown status skips the row (counted, never guessed). Items Google stops listing are left as they are.
  - **Account status:** anything but `ENABLED` → `account_not_enabled` on the account (no import). A changed currency or time zone is recorded as `account_details_changed`, never applied silently.
  - **Per-account problems** (`no_account_access`, `account_not_enabled`, `developer_token_not_approved`) end the chain with that code on the account and **never** mark the connection. Permanent errors (e.g. `bad_query`) are not retried; temporary ones are.
- **Daily figures (3-06):** after the structure, the chain reads `history_from` (13 months back) … today, **in the account's time zone**, one calendar month per step (`import_cursor` `perf:<first>:<last>`), four `searchStream` operations per month: `FROM customer`, `campaign`, `ad_group`, `ad_group_ad` with `segments.date BETWEEN …`. A 13-month first import costs about 56 operations (plus 5 for the structure).
  - Metrics: `impressions`, `clicks`, `cost_micros` (÷ 1,000,000 → exact decimal), `conversions`, `conversions_value` (doubles, kept as written; stored with 6 decimals). Selected metrics that are zero are **omitted** from Google's JSON (proto3), so a missing metric in a returned row is 0. A row with no valid date or id, a negative or non-numeric value, or a value too large to store is skipped and counted.
  - Each month **replaces** the stored rows of its days, per level, so corrections and removed activity never leave stale figures. Google sends no row for a day without activity: the account level gets a real 0 for each such day; other levels simply have no row.
  - Rows are linked to the stored campaign, ad group and ad where known; figures of entities not in the structure (e.g. a campaign with a status AdVegaX cannot read) are kept, unlinked. Ads are keyed `<ad group id>~<ad id>`. Performance Max campaigns have campaign rows but no ad-group rows; levels are never added into each other.
  - The per-connection limit (5 calls a second, burst 10) can pause a step; it is queued again with the wait and repeats its month.
- **Ongoing sync (3-07):** a scheduler tick every 5 minutes (`advegax.schedule.ads_sync`) starts the run each imported, linked account is due for — the longest first:
  - **weekly** (7 days after the last): the last 90 days, one step, 4 operations;
  - **nightly** (24 hours after the last): the last 30 days, one step, 4 operations;
  - **3-hour run:** the account and structure (5 operations) and today + yesterday (4 operations). Structure changes are picked up here; nightly and weekly runs read figures only.
  - Every re-read replaces the stored days it covers (corrections, removed activity); days outside it are never touched. Days are the account's own (its time zone). Accounts come due at their own times, so runs spread over the day.
  - A chain that has been silent for 6 hours (`ADS_CHAIN_STALE_AFTER`) is treated as dead and may be restarted.
- **Shared allowance (Q-3-2):** one developer token serves every customer, so operations are counted in one Redis counter per platform over a sliding 24 hours (`GOOGLE_ADS_DAILY_OPERATIONS`, 2,880 for Explorer; raise it to 15,000 for Basic). Each step reserves its operations first:
  - nightly and weekly re-reads stop at 80 % (`ADS_QUOTA_DEFER_SHARE`), so first imports, 3-hour runs and "Sync now" keep the rest; at 100 % every step waits;
  - a step that does not fit waits 15 minutes (`ADS_QUOTA_WAIT`) as a new, delayed job — no attempt is used, nothing is marked — and the account shows `quota_waiting`;
  - when Google answers `RESOURCE_EXHAUSTED` / `RESOURCE_TEMPORARILY_EXHAUSTED`, **every** account waits Google's `retryDelay` (or 15 minutes).
  - The counter key names only the platform (`ads-quota:google_ads`); no token is ever part of it.
- **"Sync now"** (route in 3-08): the structure and the last 30 days, never held back by the 80 % share; 6 an hour per account (`THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR`); refused while a run is going (`SYNC_IN_PROGRESS`) or when the account is not linked through an active connection (`AD_ACCOUNT_NOT_SYNCING`). An account whose first import failed starts it again.
- **Browser tests (3-10):** `tests/e2e_google_ads.py` connects simulated accounts (real sign-in, discovery, link and import with the in-process simulator; refuses deployed environments). The CI browser job switches Google Ads on with placeholder settings only to show the pages; nothing ever calls Google.
- **Health:** each 3-hour run reads the account; a run that reaches it clears earlier access problems (`no_account_access`, `account_not_enabled`, `developer_token_not_approved`). `account_details_changed` (currency or time zone changed at Google) stays as long as Google reports the different details; the stored ones are never replaced silently.
- **Requests:** headers `Authorization: Bearer`, `developer-token`, and `login-customer-id` when an account is reached through a manager. Customer ids are digits only (dashes removed) before use. `search` follows `nextPageToken` (10,000 rows a page; follow-up pages cost no operation); `searchStream` reads all batches of one answer.
- **Errors (GoogleAdsFailure `errorCode` values → plain codes):**
  - token expired or invalid → `auth_expired`; revoked → `google_sign_in_rejected`;
  - `NOT_ADS_USER` → `not_ads_user`;
  - `USER_PERMISSION_DENIED` / `CUSTOMER_NOT_FOUND` → `no_account_access`;
  - `CUSTOMER_NOT_ENABLED` → `account_not_enabled`;
  - `DEVELOPER_TOKEN_NOT_APPROVED` / `_PROHIBITED` → `developer_token_not_approved`; `DEVELOPER_TOKEN_INVALID` → `developer_token_invalid`;
  - `RESOURCE_EXHAUSTED` / `RESOURCE_TEMPORARILY_EXHAUSTED` → `quota_exhausted` (with Google's `retryDelay` when given);
  - query errors → `bad_query`; 5xx → retried; redirects and non-JSON answers → `unexpected_response`.

  Google's messages are never kept.
- **To confirm live (Step 0, PHASE_03_PLAN §4.2):** int64 JSON encoding; the error values above for each situation; PKCE and `prompt=consent` giving a new refresh token on reconnect; the revocation answer; refresh-token rules in testing mode; that `adwords` is classed as a sensitive scope.

### Meta Ads (`meta_ads`) — Phase 4, built against the simulator (live Step 0 pending)
- **Category / auth scheme:** advertising / OAuth 2.0 authorization code with **Facebook Login for Business** (a configuration id instead of a scope list; the configuration asks for `ads_read` and `business_management`), PKCE (S256, to confirm with Login for Business) and single-use state. The code is exchanged on the server, then for the **long-lived** user token (about 60 days). Long-lived tokens cannot be renewed without the person, so no token refresh is declared: when the token ends or Meta answers error 190, the connection shows "Needs reconnecting". The same Facebook account reconnecting reuses the connection (`external_account_id` = organization + Meta user id); it may also serve another organization (Q-4-11).
- **Configuration:** offered only when `META_ADS_ENABLED=true` **and** `META_APP_ID`, `META_APP_SECRET` and `META_LOGIN_CONFIG_ID` are set (secret store / local untracked settings only). The API version is `META_API_VERSION` (`v26.0`, Q-4-1).
- **Hosts:** browser → `www.facebook.com/{version}/dialog/oauth`. Server → `graph.facebook.com/{version}` only, through the SSRF-safe client; redirects are not followed.
- **Requests:** `Authorization: Bearer <token>` and `appsecret_proof` on every call. The token exchange is a `POST` with the app secret in the form body (never in the address). The person and the granted permissions come from `/me` and `/me/permissions`; `debug_token` is not used (it puts the token in the address). Lists follow Meta's `after` cursor, never its `next` URL (which repeats the token).
- **Read-only guard:** `GET` only, plus `POST /oauth/access_token`, `POST /<object>/insights` (async reports, 4-05) and `DELETE /me/permissions` (disconnect). Anything else is refused before it is sent.
- **Errors (Meta `error.code` / `error_subcode` → plain codes):**
  - 190, 102 → `meta_sign_in_rejected`;
  - 10, 200–299 → `meta_permission_missing`;
  - 4, 17, 32, 613, 80000–80014 → `rate_limited`, with Meta's `estimated_time_to_regain_access` when given;
  - 100/1487534 → `too_much_data`; 100/33 → `no_account_access`; other 100 → `bad_query`;
  - 1, 2 and 5xx → retried.

  To confirm live (Step 0 item 4).
- **Usage headers:** `x-fb-ads-insights-throttle`, `x-app-usage` and `x-business-use-case-usage` are read on every answer (highest percentage, regain estimate, access tier) for pacing in 4-06.
- **Discovery (4-03):** `GET /me/adaccounts` with `id,name,currency,timezone_name,account_status,business{id,name}`, 200 a page, following the `after` cursor (at most 5,000 accounts). Accounts are grouped by the business that owns them (`group_path` = business name; none for a personal account). `account_status` → reason shown before linking: 1, 9, 201 usable; 2 → `account_not_enabled` (disabled); 3, 8 → `account_unsettled` (unpaid balance); 7 → `account_under_review`; 100, 101, 202 and any unknown value → `account_not_enabled`. A missing or unreadable currency or time zone → `account_details_missing`. Rows without an `act_<digits>` id are skipped and counted. Linking reads the account with `GET /act_<id>` (same fields); an account the person can no longer reach is `no_account_access`. *To confirm live (Step 0 item 2): whether `me/adaccounts` includes every account reached through a business.*
- **Structure (4-04):** `GET /act_<id>/campaigns`, `/adsets` and `/ads`, 500 a page with the `after` cursor, each with `filtering=[{"field":"effective_status","operator":"IN","value":[…all 12 values…]}]` because Meta hides archived and deleted objects otherwise. Kept: campaigns (name, objective → `platform_type`, `bid_strategy`, buying type, start/stop dates as Meta writes them in the account's time zone), ad sets (stored as ad groups; optimization goal, bid strategy) and ads (name, the creative's id and name only). Status: `effective_status` ACTIVE → active; PAUSED, CAMPAIGN_PAUSED, ADSET_PAUSED → paused (a parent's pause passes down); ARCHIVED → archived; DELETED → removed; review, billing and issue states keep the configured `status` and are shown as Meta's delivery detail (`provider_extensions.delivery`). Budgets: the campaign (Advantage campaign budget) or the ad set holds it, daily or lifetime ("0" means none); amounts are in the currency's smallest unit — divided by 100, except whole units (offset 1) for CLP, COP, CRC, HUF, ISK, IDR, JPY, KRW, PYG, TWD, VND. The currency comes from the account read just before (no second call). Unreadable rows are skipped and counted. *To confirm live (Step 0 items 5–6): the effective_status values, and the budget offsets.* A status Meta adds later is not in the filter, so such objects are not returned until it is added (Step 0 lists the live values).
- **Daily figures (4-05):** `GET /act_<id>/insights` once per level (`account`, `campaign`, `adset`, `ad`) and slice, with `time_range`, `time_increment=1` (one row per day, in the account's time zone), `use_unified_attribution_setting=true` (each ad set's own attribution, as Ads Manager) and, below account level, `filtering` on `<level>.effective_status` with every status so archived and deleted objects' days are returned. Fields: `impressions`, `inline_link_clicks` (stored as clicks — link clicks, comparable with Google's clicks), `spend` (an exact decimal in the account currency; no offset), and `actions` / `action_values`, from which only `omni_purchase` is kept as purchases and purchase value (absent → a real 0; listed twice or unreadable → the row is skipped). Account totals come from Meta's account rows, which include deleted ads. Days without a row get a real zero at account level (as for Google). **Too much data** (100 / 1487534): the same request is started as an asynchronous report (`POST /act_<id>/insights`, form body), checked every 5 s up to 60 times (`GET /<report_run_id>`), then read (`GET /<report_run_id>/insights`); "Job Failed"/"Job Skipped" → `report_failed`, not done in time → `report_pending` (both retried with back-off by the job runner; the report id is never stored). *To confirm live (Step 0 items 5, 7, 8): deleted objects' insights with the filter, `omni_purchase` against Ads Manager's "Purchases", and a week of figures against Ads Manager.*
- **Ongoing sync, pacing and expiry (4-06):** the Phase 3 schedule unchanged (3-hourly, nightly 30 days, weekly 90 days). Usage headers are remembered per worker, split between AdVegaX's app (`x-app-usage`, `app_id_util_pct`) and each ad account (`acc_id_util_pct`, `x-business-use-case-usage`). From 75 % each call to that account waits 1–10 s (10 s at 95 %); from 95 %, or while Meta names `estimated_time_to_regain_access`, the account pauses without calling (`rate_limited` → the import step is held, no retry attempt used, last error `quota_waiting`, "figures will update later") for Meta's estimate or `ADS_ACCOUNT_BUSY_WAIT` (10 min). Errors 17, 32, 613, 80000–80014 pause the account; error 4 (app limit, 1504022 global load) pauses every Meta account through the Phase 3 platform block. Sign-in: no refresh; the hourly sweep records `connection.sign_in_expiring` once at 14 and once at 3 days before the end (`SIGN_IN_WARNING_DAYS`, per sign-in), and at the end marks the connection expired with `sign_in_expired` ("Needs reconnecting"); an ended sign-in is never sent to Meta. Reconnecting starts a new ~60 days. Health: an unpaid balance → `account_unsettled`, under review → `account_under_review`, disabled or closed → `account_not_enabled`, no access → `no_account_access`.
- **Disconnect:** `DELETE /me/permissions`, then our copy of the token is deleted (also when Meta cannot be reached).

### Google Analytics 4 (`google_analytics`) — Phase 5, in progress (simulator; live Step 0 pending)
- **Category / auth scheme:** analytics / OAuth 2.0 authorization code with PKCE (S256), offline access, single-use state. **The same Google Cloud project and OAuth client as Google Ads** (`GOOGLE_ADS_CLIENT_ID` / `_SECRET`, Q-5-2), but **its own connection** asking only for `https://www.googleapis.com/auth/analytics.readonly` and `openid` (for Google's stable account id `sub`; no email, name or picture). Never the edit permission. The sign-in code is shared with Google Ads (`app/providers/google/oauth.py`): token exchange, refresh before expiry, revocation on disconnect, ID-token checks. The same Google account connected to Google Ads and to Google Analytics is two connections; removing one leaves the other.
- **Switch:** `GOOGLE_ANALYTICS_ENABLED=true` plus the OAuth client; `GOOGLE_ANALYTICS_API_VERSION=v1beta` (Data API and Admin API; alpha is never used).
- **Hosts:** `analyticsadmin.googleapis.com` (discovery) and `analyticsdata.googleapis.com` (reports), through the SSRF-safe client, no redirects.
- **Read-only gate (one `_send`, static test):** `GET /v1beta/accountSummaries`, `GET /v1beta/properties/<id>`, `GET /v1beta/properties/<id>/metadata`, `POST /v1beta/properties/<id>:runReport` and `:batchRunReports`. Anything else is refused before it is sent.
- **Requests:** the token in `Authorization: Bearer` only; property ids checked (`properties/<digits>`). Every report sets `returnPropertyQuota`; the remaining tokens per day, per hour and per project per hour are kept for pacing (5-06). Account summaries follow `nextPageToken` (200 a page, at most 100 pages).
- **Errors (Google `error.status` / `details[].reason` → plain codes):** 401 / `UNAUTHENTICATED` → `google_sign_in_rejected` ("Needs reconnecting"); `SERVICE_DISABLED` → `analytics_api_disabled` (the Cloud project has not enabled the APIs — a set-up problem); `ACCESS_TOKEN_SCOPE_INSUFFICIENT` → `analytics_permission_missing`; other 403 or 404 → `no_property_access` (that property only); 429 / `RESOURCE_EXHAUSTED` → `rate_limited` (that property pauses); 400 → `bad_query`; 5xx → retry. Google's messages never travel on.
- **Discovery (5-04):** `accountSummaries` (every Analytics account and its properties) → one `properties.get` per property for its currency (ISO 4217) and IANA time zone, at most 500 properties. Properties are resources of kind `analytics_property`, grouped by their Analytics account name. A property that cannot be linked is still listed with a plain reason: `property_details_missing` (no readable currency or time zone), `property_deleted` (in Google's bin), `no_property_access` (Google refused its details; the others carry on). Entries that cannot be parsed are skipped and counted in the logs. Rediscovery updates names, groups and reasons and keeps links; a property no longer listed becomes inaccessible. A person with no Analytics access finds nothing and the connection stays active.
- **Daily reports (5-05):** one `batchRunReports` call per slice holds the three views — `date`; `date` + `sessionDefaultChannelGroup`; `date` + `sessionSource` + `sessionMedium` + `sessionCampaignName` — with `sessions`, `engagedSessions`, `totalUsers`, `newUsers`, `keyEvents`, `ecommercePurchases`, `purchaseRevenue`, ordered by every dimension, 10,000 rows a page. A view with more rows is read on with `runReport` and `offset` (at most 25 pages; the rest is marked truncated). Values are strings read exactly (`YYYYMMDD` dates in the property's time zone; money in its currency); an unreadable value is unknown, never 0; rows that cannot be read are skipped and counted; a report whose headers are not the ones asked for stops the read. `purchaseRevenue` is purchases minus refunds and can be negative. `dataLossFromOtherRow`, `subjectToThresholding`, `samplingMetadatas` and `dataTruncationReasons` become the row flags; `(other)` values are flagged too.
- **First import:** the property's details (`properties.get`), then 13 months in calendar-month slices (about 14 calls). A deleted property or one AdVegaX can no longer read stops with a plain reason on the property; a changed currency or time zone is recorded, not applied; a used-up property quota pauses only that property for 15 minutes without using a retry. Linking again re-reads the last 14 days.
- **Ongoing sync (5-06, Q-5-6):** every 3 hours today and yesterday; nightly the last 14 days; weekly the last 90; "Sync now" re-reads 14 days (6 an hour per property). Each run reads the property first. The scheduler lists imported properties with the system role's four-column grant and runs everything else under the property's organization.
- **Pacing (Q-5-7):** from each answer's `propertyQuota`: the smaller of the hour's share (`tokensPerHour` of 40,000 and `tokensPerProjectPerHour` of 14,000) and the day's share (`tokensPerDay` of 200,000). Below 25 % the next step waits 2 minutes; below 10 % the property pauses until one minute past the next full hour and shows "Google is limiting how much AdVegaX can read" (`rate_limited`); Google's `RESOURCE_EXHAUSTED` pauses it 15 minutes. No retry attempt is used and other properties carry on. Analytics 360 limits are larger and count as fully available.
- **Health on the property:** `no_property_access`, `property_deleted`, `property_details_changed`, `rate_limited`; each clears when the property answers normally again. A refused sign-in marks the connection "Needs reconnecting" and stops its properties' runs until reconnected.
- *To confirm live (Step 0, `PHASE_05_PLAN` §4.2): the JSON shapes, the demo account, errors for a removed permission and an exhausted quota, the consent screen marking for `analytics.readonly`.*

### Fake provider (`fake`) — test/local only
- **Category / auth scheme:** advertising / OAuth 2 with PKCE.
- **Resources:** two ad accounts (AUD, USD) and one store (NPR) by default; configurable.
- **Capabilities:** PKCE, token revocation.
- **Configurable failures:** auth expired, permission denied, rate limited N times, N transient failures, revoke failure.
- **Never available in staging/production** (registry refuses it).
