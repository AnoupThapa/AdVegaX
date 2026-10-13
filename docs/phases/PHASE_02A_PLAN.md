# Phase 2A — Shopify (read-only) + Finance Core: Implementation Plan

**Status:** 📝 **Draft v2 — awaiting product-owner approval** (proposed approval id A18). No Phase 2A code is written before approval. · **Date:** 2026-10-13 (v2 after independent review, §20)
**Depends on:** Phase 1 (1A, 1B, 1C implemented; awaiting review) · **Followed by:** Phase 2B (WooCommerce)
**Governing documents:** MASTER_SPECIFICATION §7, §14, §20 (D2, D4, D6, D14, D15, D17, D19, D22), ARCHITECTURE §9–§10, DATABASE_SCHEMA §5–§7, §13, §19A, INTEGRATION_GUIDES §2, `phases/PHASE_02A_SHOPIFY.md` (outline), DISCOVERY_REPORT §3 (C9, C10), §14 (Q5–Q9)

---

## 1. Objective

Let an organization connect a **Shopify store** (read-only), import its catalogue, costs, inventory, orders and refunds into AdVegaX's **platform-neutral** commerce model, keep it up to date, and show the **first deterministic store-level financial figures** — without ever showing missing data as 0 and without storing customer personal data.

At the end of 2A, on a Shopify **development store**: connect from AdVegaX (or start from Shopify) → store discovered and linked → full import → near-real-time updates by webhook plus scheduled reconciliation → products page and store revenue view → disconnect / uninstall / reconnect cleanly → privacy webhooks honoured.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all recommendations at once, or change any of them.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q5** | How will Shopify merchants connect in production? | **2A is built and tested on development stores only.** Your own stores (Eve Zone, Mediflex) can be piloted through Shopify's **custom distribution** (an install link, no App Store review) — **one Shopify app per store**, because a custom app only installs within one store or one Plus organization, and the distribution choice is permanent. The **public App Store listing is decided before launch**, with a written answer from Shopify Partner Support. | Verified 2026-10-13: App Store apps must be installed from Shopify (no typing a store address), must be embedded in Shopify admin, and **must charge through Shopify Billing**. Shopify staff say this applies even to unlisted public apps. That conflicts with AdVegaX being an independent SaaS billed through Stripe (D2, D19, D22), so it needs a business decision, not a coding decision. The 2A code is built so the App Store route can be added later without rework. |
| **Q6** | Can the same store be connected to two AdVegaX organizations? | **No — one active connection per Shopify store.** A second organization sees a clear message. Sharing a store between a business and its agency is handled later by Agency Mode (Phase 14). | Verified 2026-10-13: Shopify keeps only **one** current token per app per store. A second connection retires the first one's token, so two organizations would keep disconnecting each other. |
| **Q7** | How are store money figures defined (v1)? | **Match Shopify's own sales reports** wherever possible, so merchants see the same numbers in both places. Details in §10: refunds, cancellations and other reversals count on the day they happen; figures use the store's currency and time zone; product cost comes from Shopify's per-item cost; **if any sold item has no cost, profit shows "Not available" plus how much of revenue is costed — never a partial profit presented as complete.** | Merchants trust numbers that match Shopify. Strict missing-cost rule follows A10 (never show missing data as 0). |
| **Q8** | What customer data do we keep? | **No names, emails, phones or addresses.** Only a one-way hashed customer key (to count new vs returning customers) and the order's country code. | Keeps AdVegaX at Shopify's lower "Level 1" protected-data tier (fewer obligations); less risk. |
| **Q9** | How much history, how fresh? | First import: **the last 60 days** (no special Shopify approval needed); request Shopify's `read_all_orders` permission so production stores can import **13 months** (year-over-year). Updates: **webhooks (seconds)** plus a **reconciliation every hour** and a deeper check of the last 30 days **every night**. | Verified: orders older than 60 days need Shopify approval. Webhooks are not guaranteed, so reconciliation is required. |
| **D-2A-1** | Shopify-initiated installs (from an install link or, later, the App Store) | Supported: the person signs in to AdVegaX and picks the organization before Shopify authorization. | Needed for custom distribution now and the App Store later. |
| **D-2A-2** | When a store owner asks Shopify to erase the store (`shop/redact`, sent 48 hours after uninstall) | Delete all data imported from that store, including its daily figures; keep only audit records (which contain no customer data). | Shopify requires erasure within 30 days; simplest compliant rule. |
| **D-2A-3** | When a customer asks for erasure (`customers/redact`) | Remove the hashed customer key from that customer's orders; keep the order amounts (they contain no personal data). | Totals stay correct; nothing personal remains. |

**What I need from you before Step 0 (§4.2):** a free Shopify Partner account, one **development store** (Shopify can fill it with test products and orders), and an app created in Shopify's Dev Dashboard. I will give step-by-step instructions when you approve; the app's secret goes into a local, untracked settings file — never into chat, the repository or the browser.

## 2A. Development environment for live Shopify testing (needs your decision)

Checked 2026-10-13: **neither the cloud workspace nor the workspace on your computer can reach Shopify** (`*.myshopify.com`, `shopify.dev`) — the account's network settings block them — and Shopify must be able to reach AdVegaX over **public HTTPS** for the sign-in callback and webhooks. Everything except live testing (the code, recorded-fixture tests, the Shopify simulator, CI) works without this. Options:
- **A (recommended):** add Shopify's domains to the allowed network list (Claude settings → network access: `*.myshopify.com`, `shopify.com`, `shopify.dev`, plus the bulk-download host) and run a temporary HTTPS tunnel when testing live; or
- **B:** set up a small staging server (needs the hosting decision, Q16) — more work now, useful later anyway;
- **C:** build 2A against recorded fixtures and the simulator only, and do live testing once A or B exists (2A-01 live checks move to the end).

## 3. Scope

| Area | In scope |
|---|---|
| Shopify provider | `ShopifyProvider` (`app/providers/shopify/`) implementing `PlatformProvider` + `CommerceProvider`; GraphQL Admin API only (pinned version, §4.1); read-only scopes |
| Connect | Start from AdVegaX (store address `*.myshopify.com`) and start from Shopify (install link); authorization-code grant with `state` bound to user + organization + PKCE-like server state; callback HMAC and shop-domain checks; **expiring offline tokens** |
| Token lifecycle | Encrypted storage (existing 1B envelope encryption); background refresh with a per-store lock; reconnect and refresh never overlap; failure → connection "Needs reconnecting" |
| Webhooks | Generic webhook intake (`app/domains/webhooks/`) + Shopify verification: HMAC on raw body, size limit, de-duplication, fast 200, asynchronous processing; uninstall; three privacy webhooks |
| Import & sync | Initial import with bulk operations; incremental updates from webhooks (webhook = "this object changed" signal, then fetch it by ID); hourly + nightly reconciliation |
| Commerce model | Platform-neutral tables (§8) in `app/domains/commerce/`; Shopify-specific mapping stays in the provider (D19) |
| Finance core v1 | Deterministic `Decimal` store metrics (§10), metric-definition registry v1, cost history, `financial_daily`, golden-file tests |
| API | Read endpoints for stores, products, store metrics; Shopify connect parameters; webhook endpoints (§11) |
| UI | Connect Shopify; store page (sync status, history limit); products list/detail with cost coverage; store revenue view (§12) |
| Docs | INTEGRATION_GUIDES (Shopify entry), API_SPECIFICATION, DATABASE_SCHEMA, SECURITY, report |

## 3A. Non-goals

- Any write to Shopify (no product edits, no order changes) — read-only.
- Public App Store listing, embedded admin app, Shopify Billing (Q5 — later, if approved).
- Customer names, emails, phones, addresses; customer lists.
- Ad spend, ROAS, CPA, contribution profit (need ad platforms — Phases 3, 4, 6).
- Currency conversion across stores (Phase 6; 2A reports in each store's own currency).
- Payment/transaction fees and shipping *costs* (Shopify does not reliably expose them; shown as "Not available").
- WooCommerce (2B).

## 4. Verified platform facts and Step 0

### 4.1 Verified against Shopify documentation on 2026-10-13

| Fact | Source |
|---|---|
| API versions release quarterly; each supported ≥ 12 months. **2026-10** is the latest stable version → 2A pins `2026-10` (supported until at least 2027-10) | [API versioning](https://shopify.dev/docs/api/usage/versioning) |
| New public apps **must** use **expiring offline tokens** (`expiring=1`); all public apps by 2027-01-01. Access token 1 h; refresh token 90 days, rotated on each refresh; one current token per app per store; acquiring a new token retires the others (so acquisition and refresh must never overlap); no revocation endpoint is documented on this page | [Access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-tokens), [changelog](https://shopify.dev/changelog/posts/expiring-offline-access-tokens-required-for-public-apps-april-1-2026) |
| Standalone apps use the **authorization code grant**: `state` nonce, callback **HMAC** check (constant-time), shop must match `^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$`; refresh via `POST https://{shop}/admin/oauth/access_token` with `grant_type=refresh_token` | [Standalone apps](https://shopify.dev/docs/apps/build/authentication-authorization/authenticate-standalone-apps) |
| Orders, refunds and transactions are **protected customer data**. Level 1 applies to any use; Level 2 adds stricter rules if name, address, email or phone are used. Development stores work without review | [Protected customer data](https://shopify.dev/docs/apps/launch/protected-customer-data) |
| Orders older than **60 days** need Shopify approval and the `read_all_orders` scope | [changelog](https://shopify.dev/changelog/apps-now-need-shopify-approval-to-read-orders-older-than-60-days) |
| Rate limits: 100 points/s (Standard), 200 (Advanced), 1,000 (Plus); single query ≤ 1,000 points; cost reported in `extensions.cost` | [Rate limits](https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits) |
| Bulk queries: JSONL results with `__parentId`; up to **5 concurrent per shop** from API 2026-01; ≤ 5 connections, nesting ≤ 2 levels; result URL valid 1 week; `bulk_operations/finish` webhook (not guaranteed — poll too); max 10 days | [Bulk operations](https://shopify.dev/docs/api/usage/bulk-operations/queries) |
| Webhooks: HMAC-SHA256 of the **raw body** with the client secret, base64, header `X-Shopify-Hmac-Sha256`; 1 s connect / **5 s total** timeout; 8 retries over 4 hours, then API-created subscriptions are deleted; no ordering guarantee; de-duplicate on `X-Shopify-Webhook-Id`; Shopify recommends reconciliation jobs | [Verify](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries), [Duplicates](https://shopify.dev/docs/apps/build/webhooks/ignore-duplicates), [About webhooks](https://shopify.dev/docs/apps/build/webhooks/best-practices) |
| Privacy webhooks `customers/data_request`, `customers/redact`, `shop/redact` (48 h after uninstall); respond 2xx, **401 on bad HMAC**; act within 30 days | [Privacy law compliance](https://shopify.dev/docs/apps/build/compliance/privacy-law-compliance) |
| Product cost: `InventoryItem.unitCost` (MoneyV2, shop currency); needs `read_inventory` or `read_products`; the staff permission "View product costs" can hide it | [InventoryItem](https://shopify.dev/docs/api/admin-graphql/latest/objects/InventoryItem) |
| App Store: install only from Shopify surfaces (rule 2.3.1, no manual store address), embedded experience (2.2.2), Shopify App Pricing/Billing API (1.2.1), minimum scopes with justification incl. `read_all_orders` (3.2) | [App Store requirements](https://shopify.dev/docs/apps/launch/shopify-app-store/app-store-requirements) |
| Unlisted public apps: Shopify staff (community forum, July 2026) say a Shopify billing path is still required | [Forum thread](https://community.shopify.dev/t/can-an-unlisted-public-app-bill-clients-off-platform-or-is-shopify-billing-required/35773) — not official policy; confirm in writing (Q5) |
| Custom distribution: install link; one store or stores in one Plus organization; method cannot be changed later | [Distribution](https://shopify.dev/docs/apps/launch/distribution/select-distribution-method) |

### 4.2 Step 0 — verify on a development store before writing provider code (task 2A-01)

Prerequisite: a machine that can reach `*.myshopify.com` and a **public HTTPS address** for the API (callback and webhooks) — see §2A. In the Dev Dashboard, the app's distribution method and its protected-data fields must be chosen first (Shopify requires this even for development stores); **do not choose custom distribution on an app that may later become the public app** — the choice is permanent.

Confirm and record in INTEGRATION_GUIDES (Shopify section, dated):
1. The exact read-only scope list (proposed: `read_products`, `read_inventory`, `read_orders`, optional `read_all_orders`) — and **whether `Order.customer { id }` needs `read_customers`**. If it does, the hashed customer key (Q8) is dropped rather than adding a customer scope, unless you approve the extra scope.
2. Bulk-query shapes for products → variants → inventory item cost, and orders → line items + refunds within the nesting limits.
3. Token exchange with `expiring=1`, refresh, and the "do not acquire and refresh at once" behaviour.
4. Webhook topics available at 2026-10 for: products, inventory items/levels, orders, refunds, app uninstalled, shop update.
5. Which order fields reproduce Shopify's Sales report on the development store (golden fixture for §10) — expected: the order's sales agreements (`Order.agreements` → `SalesAgreement.happenedAt`, each `Sale` with its line type and action type), which carry orders, returns, cancellations and edits with their own dates.
5a. Whether any historical per-line cost exists (otherwise imported history uses the cost at import time — §8).
5b. Whether `read_all_orders` and expiring tokens behave the same for custom-distribution apps.
6. How an app can revoke its own access on disconnect, and the host used for bulk-result downloads (for the network allowlist).
7. Record **sanitized** fixtures (no secrets, synthetic test data only) for CI — CI never calls Shopify.

## 5. Proposed structure

```text
backend/app/
├── providers/shopify/           # Shopify-only: auth, GraphQL client, queries, bulk, mapping, webhook verification
│   ├── provider.py  auth.py  graphql.py  bulk.py  mapping.py  webhooks.py  queries/*.graphql
├── domains/commerce/            # platform-neutral: stores, products, orders, refunds, cost history, import service
├── domains/webhooks/            # generic intake: verify (via provider), dedupe, store, dispatch
├── domains/finance/             # metric registry v1, Decimal calculators, daily aggregation
frontend/features/commerce/      # store page, products, revenue view, Connect Shopify form
```

Core domains never import `providers/shopify` (existing source test extended).

## 6. Connect and token lifecycle

1. **From AdVegaX:** a manager enters `example.myshopify.com` → the existing generic `POST /organizations/{org}/connections/{provider}/start` gains an **optional body** `{ "params": { "shop_domain": … } }`, validated by the provider (anchored pattern; lower-case). **Framework change (additive):** `ConnectState`, `AuthorizationRequest` and `complete_authorization` get an optional `provider_params` field so the shop travels in the single-use server-side state; the fake provider and existing tests keep working unchanged → redirect to `https://{shop}/admin/oauth/authorize`.
2. **From Shopify (install link / later App Store):** `GET /connections/shopify/install?shop&hmac&timestamp…` → HMAC + timestamp freshness checked → browser sent to the web app's "Choose organization" page (sign-in first if needed) → step 1 continues with the chosen organization. No data is stored before the person confirms.
3. **Callback** (existing `GET /connections/{provider}/callback`): verify `state` (single use, bound to the same user), **HMAC**, shop pattern **and that `shop` equals the shop stored in `state`**; exchange the code with `expiring=1`; confirm the granted scopes include every required scope (else fail with a clear message); store tokens encrypted (1B).
4. **One store, one connection (Q6):** a new nullable `external_account_id` column on `external_connections` (additive migration) with a partial unique index on `(provider, external_account_id)` where the connection is active. Because exchanging the code would already retire the other organization's token, the check runs **before** the exchange — at `start` and again at the callback — as a narrow system-role lookup (it reveals only "connected elsewhere: yes/no"); the index is the backstop. Message: "This store is already connected to another AdVegaX organization. Ask its owner to disconnect it first."
4a. **Reconnect** by the same organization and shop **reuses** the existing connection, store and imported data (new tokens, status back to active) instead of creating duplicates — a change to the 1B `complete()` path, covered by tests.
5. **Discovery:** exactly one resource of kind `store` (shop GID, name, currency, IANA time zone). Linking it starts the initial import.
6. **Refresh:** a job refreshes when < 10 min of access-token life remains, and at least daily so the 90-day refresh token never lapses. A **per-store lock** (Redis `SET NX` + `SELECT … FOR UPDATE` on the credential row) serializes refresh and reconnect, so they never run at the same time. New access + refresh tokens are saved atomically. `invalid_grant` → connection `expired` ("Needs reconnecting"), audited with a code only.
7. **Disconnect:** delete stored tokens and stop syncs. Whether Shopify offers a way for the app to revoke its own access is checked in Step 0 (item 6); if not, the UI also tells the person to uninstall the app in Shopify.
8. **Uninstall (`app/uninstalled`):** connection `revoked`, tokens deleted, syncs stop; data is kept until `shop/redact` (D-2A-2) or until you reconnect.

## 7. Webhooks

- `POST /webhooks/shopify` (and `/webhooks/shopify/compliance`): **no session and no CSRF** — this needs a **code change**: the request-guard middleware currently applies Origin + CSRF checks to every POST, so it gains a short, explicit exempt-path list (`/api/v1/webhooks/shopify*` only) with tests proving every other route is still protected; the route-guard test allowlist is updated to match. **HMAC verified on the raw body before parsing** (constant time; 401 if invalid); body ≤ 1 MB (existing limit); topic and shop headers validated; per-IP rate limit on these routes; deliveries with a stale `X-Shopify-Triggered-At` rejected.
- After verification only the **metadata** is stored in `webhook_events` — webhook id (unique, so duplicates are ignored), topic, shop, object id, `updated_at` — and **the body is discarded**, so no customer personal data (names, emails, addresses in order payloads) is ever stored (Q8). Subscriptions also limit payload fields (`include_fields`) where Shopify allows. Acknowledged well under 5 s; processing happens in a job.
- The shop → organization lookup for an incoming webhook is a narrow system-role step; all processing then runs under that store's tenant context.
- Processing treats a webhook as **"object X changed"** and fetches the current object through GraphQL by ID. That gives one mapping path, and arrival order no longer matters. A per-object "last seen `updated_at`" guard prevents older data overwriting newer.
- Subscriptions are declared in the app configuration rather than created through the Admin API (Shopify's automatic deletion after 8 failed deliveries is documented for API-created subscriptions); the hourly reconciliation (§9) covers any gaps either way.
- Webhook metadata is kept 30 days, then deleted; bodies are never stored or logged.
- **Several Shopify apps:** custom distribution needs one app per merchant (e.g. Eve Zone and Mediflex each get their own app — Q5), so the client id/secret are looked up per app (by the app id Shopify sends) rather than assumed to be one global secret.

## 8. Data model (new tables; all tenant tables with composite tenant keys + RLS, as in 1A/1B)

| Table | Purpose | Notes |
|---|---|---|
| `stores` | Commerce extension of an `external_resources` row | provider, external store id, domain, name, currency, time zone, `history_from` (60 days / 13 months), sync status |
| `products`, `product_variants` | Catalogue | external ids as text; price as Decimal + currency; status; no descriptions/HTML beyond title (minimum data) |
| `inventory_levels` | Available quantity per variant (summed across locations) | `available` + availability state |
| `product_cost_history` | Effective-dated unit cost per variant | each change from Shopify adds a row; order lines take the cost **valid at order time**. History starts at the first import: orders imported from before that use the cost at import time and are **marked "cost at import"** (shown in the revenue view) unless Step 0 finds historical cost |
| `orders`, `order_items` | Orders and lines | store-currency (`shopMoney`) amounts; `customer_key` (hashed, nullable — Q8); country code; test orders excluded |
| `sales_entries` | Normalized sales agreements: each sale/reversal with its own date, line type (product, shipping, tax, duty, fee, discount, gift card) and action (order, return, cancel, edit) | the source for §10, so figures match Shopify's report dates |
| `refunds`, `refund_items` | Refunds (for display and inventory/cost of returns) | |
| `webhook_events` | Intake log (metadata only, no body) | system-role only; deleted after 30 days |
| `commerce_sync_state` | Per-store cursors | last reconciliation time, bulk operation id, last error code |
| `financial_daily` | Additive daily components per store (DATABASE_SCHEMA §13) | `definition_version` (e.g. `finance-v1`), availability per component, cost coverage |

Additive change to an existing table: `external_connections.external_account_id` (+ partial unique index). Migrations 0007+ (one per task); each with upgrade/downgrade tests (existing migration test suite). Hashing for `customer_key`: HMAC-SHA256 with a per-organization key held in the encrypted key ring, so keys cannot be matched across organizations.

## 9. Import and sync

- **Initial import** (job `commerce.initial_import`): bulk query for products → variants → inventory item (cost, quantity); bulk query for orders since `history_from` → line items, refunds. JSONL streamed line by line (bounded memory), mapped, upserted in batches by external id. Progress and errors are visible on the store page.
- **Incremental:** webhook jobs (§7).
- **Reconciliation:** hourly — orders and products with `updated_at` ≥ last run − 10 min overlap; nightly — last 30 days of orders re-checked. A difference fixes data and is counted in sync metrics.
- **Rate limiting:** cost-aware token bucket per shop using `extensions.cost.throttleStatus` (existing 1B limiter extended); a throttle becomes a retryable error with back-off.
- **HTTP client extensions (2A-06):** the 1B safe client reads whole responses (10 MiB cap) and has no per-provider host list. 2A adds a **streaming download** (bounded chunks, overall size/time limits) for bulk JSONL results and a **per-provider host allowlist** (validated `*.myshopify.com` + the bulk-download host found in Step 0).
- **Re-computation:** any changed order or refund marks its store-day(s) dirty; `finance.recompute_daily` rebuilds those days from stored rows (idempotent).

## 10. Finance core v1 (Q7) — store-level only

All amounts are `Decimal` in the store's currency (`shopMoney`), days in the store's time zone, rounding half-even to the currency's minor unit **only for display**; definitions live in one registry (`finance-v1`), never in screens (MASTER §7).

Built from the normalized sales agreements (`sales_entries`), mirroring Shopify's Sales report (help.shopify.com, verified 2026-10-13): sales are dated to the order date; **reversals** (returns, cancellations, edits, refunded shipping/tax/fee adjustments) are dated to the day they were processed. Cancelled orders count in gross sales and their cancellation is a reversal.

| Metric | Definition v1 |
|---|---|
| Gross sales | Product price × quantity before taxes, shipping, discounts and reversals (product lines only; excludes gift cards, test and deleted orders); order date |
| Discounts | Line-item discounts + each line's share of order-level discounts (shipping discounts belong to Shipping); order date |
| Sales reversals | All product-line adjustments with negative value (returns, cancellations, edits, discount adjustments); **processing date** |
| Net sales | Gross sales − discounts − sales reversals |
| Shipping | Shipping charges − shipping discounts − refunded shipping |
| Taxes, duties, fees | As recorded on the sales agreements (duties only when the store collects them) |
| Total sales | Net sales + taxes + duties + shipping + fees (matches Shopify's "Total sales") |
| Orders | Count of non-test orders on order date |
| Product cost (COGS) | Σ quantity × unit cost valid at order time, minus cost of reversed quantities on the reversal date |
| Gross profit | Net sales − COGS, **only when every line in the period has a cost**; otherwise "Not available" with **cost coverage** (share of net sales with known cost) |
| Gross margin | Gross profit ÷ net sales (computed on read; "Not available" if either side is) |
| Shipping cost, payment fees | **Unavailable** in 2A (shown as "Not available", never 0) |
| New vs returning customers | From the hashed key; "Not available" when a key is missing (Q8) |

**Golden tests:** hand-calculated fixtures (discounts, partial refunds, refunds in a later month, cancelled orders, order edits, refunded shipping, duties, multi-currency presentment, missing cost, cost change mid-period, time-zone day boundaries, DST change) must match to the cent; plus a fixture reproduced from the development store's own Sales report (Step 0, item 5).

## 11. API (additions to API_SPECIFICATION; envelope, errors, auth, RLS and route guards as today)

| Method & path | Who | Purpose |
|---|---|---|
| `POST /organizations/{org}/connections/shopify/start` (body `{shop_domain}`) | owner, admin, manager | Additive: provider-specific connect parameters |
| `GET /connections/shopify/install` | public (HMAC-verified) | Shopify-initiated install entry |
| `POST /webhooks/shopify`, `POST /webhooks/shopify/compliance` | public (HMAC-verified) | Webhook intake |
| `GET /organizations/{org}/stores`, `…/stores/{id}` | all members | Stores with sync status and history limit |
| `GET /organizations/{org}/stores/{id}/products` (cursor, search, status) / `…/products/{id}` | all members | Catalogue with cost and inventory availability |
| `GET /organizations/{org}/stores/{id}/metrics/daily?from&to` | all members | Daily components + derived metrics with availability, `definition_version` |
| `POST /organizations/{org}/stores/{id}/resync` | owner, admin, manager | Queue reconciliation (rate-limited) |

The existing route-guard sweep covers the new routes automatically; the three public routes are added to its allowlist with dedicated HMAC tests.

## 12. Web app

- **Connections:** "Connect Shopify" asks for the store address (with help text), then goes to Shopify. A "Choose organization" page serves Shopify-initiated installs.
- **Store page:** sync status ("Importing… 40 %", last updated, problems in plain words), history limit ("Showing orders from 14 Aug 2026 — older orders need Shopify approval").
- **Products:** searchable list with price, inventory and cost ("Not set in Shopify" when missing) and a cost-coverage banner.
- **Revenue view:** date-range totals and a daily table/chart for the metrics in §10; every unavailable value says why; numbers labelled with currency and time zone.
- Same standards as Phase 1C: axe 0 serious/critical, keyboard-only, nonce CSP, no browser storage; e2e journey extended using a **Shopify simulator** (a local test double that speaks the recorded GraphQL/OAuth/webhook formats) — never real Shopify in CI.

## 13. Security and privacy controls (additions to SECURITY.md)

- Client secret only in settings/secret store; tokens encrypted (1B); never logged, returned or shown; extend `tests/security/test_credentials.py` to Shopify tokens and webhook payloads.
- All Shopify calls through `SafeHttpClient`, with the new per-provider host allowlist: `*.myshopify.com` (validated shop) and the bulk-result download host from Step 0 only.
- **Bulk-result URLs are bearer links** (signed, valid a week): never logged, stored only until downloaded, redacted from errors.
- HMAC checks (callback, install, webhooks) constant-time; replay limited by timestamp freshness (install) and webhook-id de-duplication.
- Minimum scopes, read-only; scope check after authorization.
- Protected customer data Level 1 controls: minimum data (Q8), purpose stated in the app's data-protection details, retention (webhook metadata 30 days; store data until erasure), encryption in transit/at rest, privacy webhooks honoured and audited. **Before any merchant other than you uses it:** a privacy policy and a data-protection agreement with merchants (Level 1 requirement) — a business/legal deliverable, listed in §17.
- Tenant isolation: new tables in the RLS and cross-tenant test suites; webhook processing runs under the store's tenant context.

## 14. Testing

- Provider contract tests on recorded fixtures: auth, refresh (incl. rotation and expiry), error mapping (401, 403, 404, 429/throttled, 5xx, timeouts), bulk JSONL parsing, mapping.
- Webhooks: valid/invalid HMAC, oversize, duplicates, out-of-order updates, unknown shop, uninstall, all three privacy topics.
- Token refresh race test (parallel refresh + reconnect never leaves an invalid token in use).
- Finance golden tests (§10); property tests for additivity of daily components.
- Tenant isolation and route-guard sweeps; migrations up/down.
- Frontend unit + e2e (simulator) with axe; coverage gates unchanged (85 % / 95 % security-critical).

## 15. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 2A-01 | Step 0 verification on the development store; Shopify section in INTEGRATION_GUIDES; sanitized fixtures |
| 2A-02 | Data model and migrations (§8), RLS, isolation tests |
| 2A-03 | Shopify connect: start with store address, Shopify-initiated install, callback checks, expiring tokens, discovery, one-store-one-connection |
| 2A-04 | Token lifecycle: refresh with locking, failure states, disconnect/uninstall |
| 2A-05 | Webhook intake (generic + Shopify): middleware exemption, HMAC, de-duplication, metadata-only storage; uninstall and privacy webhooks recorded (processing follows in 2A-07) |
| 2A-06 | HTTP client extensions (streaming, host allowlist); GraphQL client; initial import with bulk operations; normalizers; sales agreements; cost history |
| 2A-07 | Webhook processing (fetch changed object), incremental sync and reconciliation; cost-aware rate limiting; erasure jobs |
| 2A-08 | Finance core v1, `financial_daily`, golden tests |
| 2A-09 | Read API and OpenAPI/types |
| 2A-10 | Web app: Connect Shopify, store page, products, revenue view |
| 2A-11 | Shopify simulator, e2e + accessibility, docs, `PHASE_02A_REPORT.md` |

Estimate: **3–4 weeks** including your reviews (ROADMAP §7). Step 0 can start the day the development store exists.

## 16. Acceptance criteria

1. A development store connects from AdVegaX and from an install link, imports, stays in sync (webhook + reconciliation), and survives disconnect, uninstall, reinstall and token expiry without manual database work.
2. Finance figures match hand-calculated golden fixtures to the cent and match the development store's Sales report for the verified fixture.
3. No customer name, email, phone or address is requested or stored; privacy webhooks are honoured and audited.
4. Tokens never appear in responses, logs, audit, UI or AI context; all new routes pass tenant-isolation and route-guard sweeps.
5. Missing data is never shown as 0 (cost, fees, shipping cost, history beyond the allowed window).
6. All suites pass (backend `make check`, frontend check, e2e + axe) with no live Shopify calls in CI.

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Production distribution path (App Store rules vs independent SaaS + Stripe) | **HIGH** (business) | Q5: develop on development stores; custom distribution for pilots; written Shopify answer before launch |
| `read_all_orders` approval refused or slow | MEDIUM | 60-day default works; UI states the limit |
| Missing product costs in real stores make profit "Not available" often | MEDIUM | Cost-coverage indicator; later phase may allow manual cost entry (your decision then) |
| Token refresh races | MEDIUM | Single per-store lock; race test |
| Webhook loss | MEDIUM | Hourly + nightly reconciliation |
| No machine that can reach Shopify / receive webhooks (current network settings block Shopify; no public HTTPS address) | **HIGH (blocks live testing)** | §2A: allow Shopify domains in network settings + a tunnel, or a staging server |
| Privacy policy and merchant data-protection agreement missing | MEDIUM (before other merchants) | Business/legal task before any third-party merchant connects |
| Shopify API changes (quarterly) | LOW | Pinned version; upgrade task each year with fixture refresh |
| Number mismatch with Shopify reports | MEDIUM | Definitions copied from Shopify's reports; golden fixture from the development store |

## 18. Rollback

All 2A tables are new (migrations reversible); the provider is registered behind configuration (absent client id → not offered). Removing the provider and running the 2A down-migrations restores Phase 1 behaviour. Phase 1 changes are additive: `external_connections.external_account_id`, an optional start body, optional `provider_params` in connect state, and the webhook path exemption in the request-guard middleware — each with tests and a reversible migration where applicable.

## 19. Approval checklist

Approve or change: **Q5, Q6, Q7 (§10), Q8, Q9, D-2A-1, D-2A-2, D-2A-3, the live-testing environment option (§2A)**, the read-only scope list (§4.2-1), API version 2026-10, and task-by-task delivery 2A-01 … 2A-11. No new runtime packages are proposed (stdlib HMAC; existing HTTP client); any later need will be asked for first.

## 20. Review record (v2, 2026-10-13)

An independent review (code, docs and Shopify documentation) found issues in v1; all are fixed in this version:
1. Webhooks would have been blocked by the existing CSRF/Origin middleware → explicit exempt-path list with tests (§7).
2. One-store-one-connection check ran after the token exchange, which would already disconnect the other organization; no column existed to enforce it → `external_account_id` + pre-exchange check (§6.4).
3. The 1B connect flow cannot carry the shop → additive `provider_params` (§6.1).
4. Storing webhook bodies would store customer personal data → metadata only (§7).
5. Finance definitions used Shopify's deprecated "Returns" → "Sales reversals" from sales agreements, dated when processed; shipping, duties, fees (§10).
6. Cost at order time unavailable for imported history → marked "cost at import" (§8).
7. Custom distribution = one app per merchant and a permanent choice → per-app secrets; warning in Step 0 (§4.2, §7).
8. Reconnect would duplicate data → reuse (§6.4a).
9. Safe HTTP client cannot stream or allowlist hosts → added to 2A-06 (§9).
10. Task order: webhook processing moved after the GraphQL client (§15).
11. Live-testing environment blocked → §2A (your decision).
12. Smaller items: token-retirement wording, privacy/DPA prerequisite, webhook replay check, bulk URLs treated as secrets.

