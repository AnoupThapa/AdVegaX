# Phase 2B — WooCommerce (read-only): Implementation Plan

**Status:** 📝 **Draft — awaiting product-owner approval.** Nothing in this plan is implemented. · **Date:** 2026-10-14
**Depends on:** Phase 2A (implemented against the simulator; awaiting review) · **Followed by:** Phase 3 (Google Ads) per ROADMAP
**Governing documents:** MASTER_SPECIFICATION §7, §14, §20 (D4, D6, D14, D15, D19, D22), ARCHITECTURE §9–§10, DATABASE_SCHEMA §4A, INTEGRATION_GUIDES §2, `phases/PHASE_02B_WOOCOMMERCE.md` (outline), `phases/PHASE_02A_PLAN.md` and `PHASE_02A_REPORT.md`, DISCOVERY_REPORT §10, §14 (Q10), risk 6 (SSRF, CRITICAL)

---

## 1. Objective

Let an organization connect a **self-hosted WooCommerce store** read-only. Its products, stock, costs, orders and refunds are imported into the **same** platform-neutral commerce model and finance core that Shopify uses, and kept up to date. Missing data is never shown as 0, and no customer personal data is stored.

This phase also proves the abstraction. **The same sales, entered in a Shopify store and in a WooCommerce store, must produce identical daily figures** (parity tests).

At the end of 2B, on a WooCommerce test site:

- the merchant enters their store address and approves read-only access in WordPress;
- the store is discovered, linked and fully imported;
- it stays up to date by scheduled checks;
- the products page and revenue view work;
- disconnect, a revoked key, an unreachable site and reconnect are all handled cleanly.

Unlike Shopify, WooCommerce runs on the merchant's own server. AdVegaX will call addresses that merchants type in, which is why **SSRF** (tricking our server into calling internal addresses) is the phase's critical risk.

## 2. Decisions needed from you (plain language)

Each has a recommendation. You can approve all recommendations at once, or change any of them.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q10a** | Which WooCommerce versions do we support? | **WooCommerce 9.0 or newer** (released mid-2024, so a little over two years of releases), checked when connecting. Older stores see "Please update WooCommerce to connect." | The parts 2B needs (REST API v3 and its "modified after" filters) are expected to be present well before 9.0; Step 0 confirms on 9.0. Supporting older versions adds testing for few stores. WooCommerce itself is moving to PHP 8.1+ in Feb 2027, so old stores will shrink. |
| **Q10b** | Do we accept stores without HTTPS? | **No — HTTPS only, and only addresses on the public internet.** | API keys travel with every request. Over plain HTTP they would need OAuth signing and could still leak; refusing HTTP also closes several SSRF tricks. Almost every live store already has HTTPS. |
| **Q-2B-1** | Where does product cost come from? | **WooCommerce's own "Cost of Goods Sold" feature** (built in since 10.3, Oct 2025; the merchant switches it on). It records cost **on each order at the time of sale**. When it is off, or for orders placed before it was switched on, cost shows **"Not available"** with the usual coverage figure. Cost plugins and manual entry come later, if you want them. | Native COGS gives order-time cost, which is better than Shopify's (Shopify only has today's cost). Plugins each store cost differently, so supporting them is a separate job. |
| **Q-2B-2** | Which orders count as sales? | **Match WooCommerce Analytics' defaults:** count orders in every status except *pending payment, failed, cancelled*, drafts and trash. Refunds count on the day they are made. | Merchants compare with WooCommerce's own reports. A store can change those settings, but read-only access cannot see them; the store page says which statuses are counted. |
| **Q-2B-3** | How fresh, and with webhooks? | **Scheduled checks only: every 15 minutes** (orders and products changed since the last check) **plus a nightly full check.** No webhooks in 2B. | Read-only keys **cannot create webhooks** (that needs write access, which we never ask for). WooCommerce webhooks also switch themselves off after 5 failed deliveries. 15-minute checks are simple and reliable; webhooks could be added later as an optional speed-up. |
| **Q-2B-4** | How much history? | **13 months** on first import (same as Shopify with approval, Q9). | WooCommerce has no history limit, and year-over-year needs 13 months. |
| **Q-2B-5** | Orders in another currency (multi-currency plugins)? | **Imported but not added into the figures.** A day that has such orders shows its figures as "Not available — orders in other currencies" until currency conversion arrives (Phase 6). | Adding mixed currencies would give wrong totals; leaving them out silently would understate (A10). |
| **Q-2B-6** | What if the store's web host strips the login header? | **Show a clear fix guide; never fall back to sending the key in the web address.** | WooCommerce allows putting the key in the URL as a fallback, but URLs end up in server logs and proxies. |
| **Q-2B-7** | Disconnect | AdVegaX deletes its copy of the key. **The page tells the merchant to also revoke the key** in WooCommerce → Settings → Advanced → REST API. | A read-only key cannot delete itself. |

## 2A. Test environment (needs your decision)

Checked 2026-10-14: this workspace **cannot download WordPress or WooCommerce** (`wordpress.org` and `downloads.wordpress.org` are blocked by the network settings). PHP is installed, so a local test store could run here if the downloads were allowed. Options:

- **A (recommended):** allow `wordpress.org`, `downloads.wordpress.org` and `api.wordpress.org` in Claude's network settings. I then run a **local WooCommerce test store inside the workspace** for Step 0 and for repeatable contract tests. No public address, tunnel or hosting is needed, which is easier than Shopify.
- **B:** a WooCommerce contract-test job in GitHub CI (a WordPress + WooCommerce container on each pull request). This needs no settings change, but results are only visible on GitHub runs.
- **C:** like 2A, build against WooCommerce's documentation and a simulator only, and confirm on a real store later.

A and B can be combined: A for building, B to keep it checked.

## 3. Scope

| Area | In scope |
|---|---|
| WooCommerce provider | `WooCommerceProvider` (`app/providers/woocommerce/`) implementing `PlatformProvider` + `CommerceProvider`; REST API `wc/v3`; HTTP Basic auth over HTTPS; read scope only |
| Connect | The merchant enters the store address → validated and normalized → redirected to the store's `/wc-auth/v1/authorize` (scope `read`) → the store **posts the key to AdVegaX** (server to server) → the browser returns to the web app. Capability check at connect: WooCommerce version, REST reachable, header not stripped, COGS on/off, currency, time zone |
| SSRF hardening | Every call goes through the existing `SafeHttpClient`, with new per-store rules: HTTPS only; DNS checked on **every** request (no private, loopback, link-local or metadata addresses); no redirects to other hosts; strict size and time limits; no credentials in URLs |
| Import framework | **Paged import** next to Shopify's bulk exports: one page per job step, cursor kept in the sync state, so the existing one-step-at-a-time chain, locks and progress work unchanged |
| Import & sync | Products and variations (price, SKU, stock, cost); orders since the history window (lines, shipping, fees, taxes, discounts, order-time cost); refunds (line items, amounts, dates). 15-minute and nightly checks; "Sync now" |
| Store health | Unreachable, key revoked or user deleted, header stripped, WooCommerce too old, COGS switched off — shown in plain words on the store page |
| Finance | WooCommerce mapping into the existing `finance-v1` definitions; **parity tests** with the Shopify fixtures; status rule (Q-2B-2); currency rule (Q-2B-5) |
| API / UI | Connect form for WooCommerce (store address); store health on the store page; everything else reuses the 2A Stores pages |
| Testing | WooCommerce simulator (like 2A's), SSRF suite extensions, parity tests, journey test, browser test; live contract checks per §2A |
| Docs | INTEGRATION_GUIDES (WooCommerce entry), API_SPECIFICATION, DATABASE_SCHEMA, SECURITY, report |

## 3A. Non-goals

- Any write to WooCommerce (no edits, no webhooks created, no write keys).
- Cost plugins (e.g. third-party COGS plugins) and manual cost entry (later, if you want them).
- Customer names, emails, phones, addresses, customer lists.
- Webhooks (Q-2B-3), WordPress plugin of our own, WooCommerce Marketplace listing.
- Currency conversion (Phase 6), ad data (Phases 3–4).
- Stores without HTTPS or on private networks (Q10b).

## 4. Verified platform facts and Step 0

### 4.1 Verified against WooCommerce documentation on 2026-10-14

1. **Authorization endpoint** `/wc-auth/v1/authorize`, query parameters:
   - `app_name`, `scope` (`read` | `write` | `read_write`), `user_id`, `return_url`, `callback_url` (all required);
   - `user_id` is **our own** reference and is echoed back, so it carries the single-use connect nonce;
   - the docs say `callback_url` should use HTTPS.
2. **Key delivery:** the store **POSTs JSON** to `callback_url` with `key_id`, `user_id`, `consumer_key`, `consumer_secret`, `key_permissions`. The browser is then sent to `return_url` with `success=1|0` and `user_id`.
3. **Authentication over HTTPS:** HTTP Basic auth with the consumer key and secret.
   - The documented fallback puts them in the query string for servers that drop the `Authorization` header; we will not use it (Q-2B-6).
   - Keys act with the permissions of the WordPress user who approved them, and stop working if that user is deleted.
   - Keys do not expire.
4. **Orders** `GET /wp-json/wc/v3/orders`:
   - Filters: `after`/`before`, `modified_after`/`modified_before`, `dates_are_gmt`, `status` (pending, processing, on-hold, completed, cancelled, refunded, failed, trash), `page`/`per_page`, `orderby`, `order`, `dp`.
   - Order totals are strings: `discount_total`, `discount_tax`, `shipping_total`, `shipping_tax`, `cart_tax`, `total`, `total_tax`, `prices_include_tax`, `currency`.
   - Dates: created / modified / paid / completed, each in site time and GMT.
   - Line items carry `subtotal` (before discounts), `total` (after discounts), their taxes, `quantity`, `product_id`, `variation_id`, `sku`. There are also shipping, fee, tax and coupon lines, and refund summaries.
   - **Orders include billing and shipping addresses and the customer's email and phone, which AdVegaX must drop on arrival and never store.**
5. **Refunds** `GET /wp-json/wc/v3/refunds`: lists refunds across orders, with `parent_id`, `date_created_gmt`, `amount`, `reason`, line items (product, variation, quantity, totals, taxes), `after`/`before` and paging.
6. **Products** `GET /wp-json/wc/v3/products`:
   - Filters: `modified_after`, `dates_are_gmt`, `status`, `type` (simple, grouped, external, variable).
   - Fields: `sku`, `price`, `manage_stock`, `stock_quantity`, `stock_status`, `variations`, `date_modified_gmt`.
   - Variations come from `/products/<id>/variations`; a cross-product `/variations` endpoint exists since 10.3.
7. **Cost of goods (native)**, core since WooCommerce 10.3 (Oct 2025), **off by default**:
   - products and variations expose `cost_of_goods_sold` (`values`, `total_value`);
   - orders expose `cost_of_goods_sold.total_value`, and line items `cost_of_goods_sold.value`;
   - refunds carry negative cost values;
   - order cost is **fixed at the time of the order**; orders placed before the feature was switched on have none.
8. **System status** `GET /wp-json/wc/v3/system_status`: WooCommerce `version`, `wp_version`, `site_url`/`home_url`, store `currency` and `number_of_decimals`, and whether the connection is secure.
   - Its `default_timezone` is the **server's** zone, not necessarily the store's.
   - **The store's time zone** is in the public WordPress REST index (`/wp-json/`: `timezone_string`, `gmt_offset`).
9. **Webhooks** (for reference; not used in 2B): `X-WC-Webhook-Signature` is a base64 HMAC-SHA256 of the body. Creating webhooks needs write access, and a webhook is disabled after 5 consecutive failures.
10. **WooCommerce Analytics default excluded statuses:** pending, failed, cancelled; `auto-draft` and trash are always excluded.
11. **Versions:** WooCommerce 11.x is current. 11.6 (Feb 2027) will require PHP 8.1+.

### 4.2 Step 0 — verify on a test store before writing provider code (task 2B-01)

1. Does WooCommerce refuse an `http://` or local `callback_url`? What does it do if our callback fails, and is the key still created?
2. Can a `read` key call `system_status`, and the WordPress index for the time zone?
3. Does `_fields` (the WordPress option to return only chosen fields) work on orders and refunds, so customer details are **not even sent**?
4. What is the maximum `per_page` (expected 100)? Do paging headers `X-WP-Total` and `X-WP-TotalPages` work?
5. Are line `total`s always without tax, including when prices are entered with tax?
6. How do refunds without line items (amount only) look, and how is their tax split?
7. Do cost fields appear on orders and refunds exactly as documented, both with COGS switched on and switched off?
8. Do `modified_after` on orders and products catch status changes, refunds and stock changes?
9. How do orders in a second currency look with a common multi-currency plugin?
10. **Sales-report match:** our daily figures for a fixed set of orders must equal WooCommerce Analytics → Revenue for the same days.

## 5. Proposed structure

```text
backend/app/
├── providers/woocommerce/        # WooCommerce-only: store URL rules, auth flow, REST client, paging, mapping
│   ├── provider.py  stores.py  client.py  mapping.py
├── domains/commerce/             # gains the paged-import step (platform-neutral)
├── domains/integrations/         # gains the key-delivery callback (generic "platform posts credentials")
frontend/features/connections/    # WooCommerce connect fields (store address)
frontend/features/stores/         # store health
```

The core still never imports `providers/woocommerce` (static test D19 extended).

## 6. Connect, credentials and store health

1. **Start:** a manager enters the store address.
   - It is normalized (lower-case host; `https://` added; trailing slash and `/wp-admin` removed). WordPress in a sub-folder (`example.com/shop`) is allowed.
   - It is validated: HTTPS, a public host name, no user name or password in the URL, no unusual port.
   - The existing `POST /organizations/{org}/connections/woocommerce/start` with `{params: {store_url}}` returns the store's `/wc-auth/v1/authorize` address (scope `read`, our `callback_url` and `return_url`, `user_id` = single-use connect nonce).
   - Before redirecting, AdVegaX checks that the store answers `/wp-json/` and has the WooCommerce `wc/v3` namespace. This gives a clear message instead of the person landing on a broken page.
2. **Key delivery** (new, generic): `POST /api/v1/connections/{provider}/credentials`. **No session and no CSRF**, like webhooks: the exemption is for that exact path and covered by tests.
   - It accepts JSON only, at most 4 KB, and is rate-limited per IP.
   - The `user_id` must match an **unused, unexpired connect nonce**, which is consumed at once. The key must be `read` only (anything else is refused and not stored).
   - The key is then **verified by calling the store** that was recorded in the nonce. The posted body never decides which store is called.
   - Only after that is the key stored encrypted (1B).
   - The answer never echoes anything back.
3. **Return:** the browser comes back to the web app (`/connect/woocommerce/return`) with `success` and the nonce. The page shows "Connected" (or the reason) by reading the connection status. It never trusts the query string alone.
4. **One store, one connection:** the same rule as Shopify. The store's normalized address is the `external_account_id`, and the check happens at `start`.
5. **Discovery:** one `store` resource with its name, currency and decimals, the time zone from WordPress, and the WooCommerce version. Too old → refused with "Please update WooCommerce to 9.0 or newer" (Q10a).
6. **Health** (shown on the store page, never as an error code):
   - store unreachable;
   - key refused (revoked, or the WordPress user was deleted) → "Needs reconnecting";
   - login header stripped by the host → guide (Q-2B-6);
   - WooCommerce below the minimum;
   - COGS switched off → "Cost not available — switch on Cost of Goods Sold in WooCommerce".
7. **Disconnect:** the stored key is deleted, syncs stop, and the page asks the merchant to revoke the key in WooCommerce (Q-2B-7). Reconnect reuses the connection and data, as in 2A.

## 7. SSRF and outbound safety (CRITICAL)

- One path for every call: `SafeHttpClient` with a WooCommerce policy.
  - HTTPS only; port 443, or another port only if you approve one later.
  - The host name is resolved **on every request**, and private, loopback, link-local, multicast, CGNAT, metadata and IPv6 local ranges are refused. The connection is pinned to the checked address, so DNS rebinding fails.
  - **Redirects are not followed.** A redirect to the same store's canonical address (e.g. `www.`) is reported, so the person can re-enter it.
  - Response size and time limits; JSON only.
- The store URL is a stored value, never taken from a request after connect. Every call is built from it plus a fixed path.
- Credentials never appear in URLs, logs, errors, audit or responses. Store response bodies never enter errors or logs.
- Per-store request limiter (default 2 requests per second) and back-off on 429 or 5xx, because small shared hosts fall over easily.
- The existing SSRF test suite is extended: rebinding, redirect chains, IPv6, decimal and octal IP forms, `user@host` tricks, sub-folder paths, and a store answering with huge or slow bodies.

## 8. Data model (additive migration 0010)

- `stores`:
  - `site_url` (normalized base URL, for WordPress in a sub-folder);
  - `platform_version`;
  - health fields: `health_code`, `health_checked_at`;
  - `counted_statuses` (the Q-2B-2 rule recorded with the store, so the page can say it).
- `commerce_sync_state`: a paged-import `cursor`, plus `last_modified_seen` for the 15-minute checks.
- `orders`: `excluded_reason` (`status` | `other_currency`), so figures can explain what is left out.
- **No new customer fields.** Value lists are extended only where WooCommerce needs a value Shopify did not have. Line types (product, shipping, fee, tax) and actions (order, return) already fit.
- The product status mapping is proposed as: publish → active; draft and pending → draft; private → unlisted; trash or deleted → deleted.

## 9. Import and sync

- **Paged import (framework, platform-neutral):** a provider either supports bulk exports (Shopify) or paged reads (WooCommerce, new `Capability.PAGED_IMPORT`). For paged reads, the import chain runs **one page per job step**: products, then variations, then orders, then refunds. The cursor is saved after each page, so a stopped import resumes where it was. Shopify's path is unchanged and its tests must still pass untouched.
- **Initial import:** the catalogue, then orders created in the last 13 months (Q-2B-4), then refunds in the same window. Page size: up to 100 (Step 0 item 4).
- **15-minute check:** products and orders with `modified_after` = last check minus an overlap (default 10 minutes, in settings), plus refunds created since then. A "newer wins" guard (from 2A) means overlaps are harmless.
- **Nightly check:** the whole catalogue, plus orders and refunds from the last 30 days. Products missing from the full list are marked deleted; orders are never deleted on absence, only when their status is trash.
- **Customer data:** the mapper keeps only what the commerce model has. Billing and shipping objects are dropped before anything is stored or logged; `_fields` will also stop them being sent if Step 0 confirms it works.
- **"Sync now"** runs the nightly-style check, with the same per-store limit as Shopify.

## 10. Finance mapping (finance-v1, same definitions as Shopify)

| Figure | WooCommerce source (to confirm in Step 0) |
|---|---|
| Order date / day | `date_created_gmt` → the store's time zone (WooCommerce Analytics' default date type) |
| Gross sales | Σ line `subtotal` (before discounts, without tax) |
| Discounts | Σ (line `subtotal` − line `total`) |
| Sales reversals | Refund line items (negative), dated by refund `date_created_gmt`. Amount-only refunds are counted in full, with their tax split if WooCommerce provides it (Step 0 item 6) |
| Net sales | Gross − discounts + reversals (the same formula as Shopify) |
| Shipping, taxes, fees | `shipping_lines`, `total_tax` and `tax_lines`, `fee_lines` |
| Cost of goods | Line `cost_of_goods_sold.value` (order time); refunds negative. "Not available" when any counted line has no cost (Q7 rule) |
| Orders counted | Statuses per Q-2B-2; other-currency orders per Q-2B-5 |

**Parity tests:** the sample store used in the Shopify tests is entered as an equivalent WooCommerce store in the simulator. Both must give **identical** daily figures, to the cent.

## 11. API

- `POST /connections/woocommerce/start` with `params.store_url` (existing generic route).
- New `POST /connections/{provider}/credentials` (key delivery, §6.2), documented like the webhook route and kept out of the web app's schema.
- Store responses gain `health` (code, plain message key, checked at) and `counted_statuses`. Everything else is the 2A read API unchanged.

## 12. Web app

- **Connections page:** WooCommerce asks for the store address, using the same form as Shopify's.
- **Return page:** "Connected — importing now", or the reason it failed (refused by the merchant, store unreachable, old version, header stripped).
- **Store page:** a health panel with the fix in plain words; "Counted: all orders except pending payment, failed and cancelled"; cost hint when COGS is off.
- No new pages otherwise. Products and revenue views work for any provider.

## 13. Security and privacy (additions to SECURITY.md)

- **SSRF:** §7. **Credentials:** encrypted at rest; never echoed, logged or audited; the key-delivery route is single-use and nonce-bound, and verifies the key against the stored store URL before saving.
- **Customer data:** dropped at the mapper; test fixtures include full billing and shipping details, to prove they never reach the database, logs or responses.
- **Exempt routes:** exactly two patterns (webhooks from 2A, key delivery), with tests that every other POST still needs a session and CSRF.

## 14. Testing

- **WooCommerce simulator** (in-process, like 2A's): the authorize redirect, key delivery, REST paging, products, variations, orders, refunds, system status, the WordPress index, 401/404/429/5xx, header stripping, slow or huge bodies, multi-currency orders, COGS on and off.
- **SSRF suite extensions** (§7).
- **Parity tests** (§10).
- **Journey test:** connect → import → 15-minute change → refund → key revoked → reconnect → disconnect.
- **Browser test:** a simulated WooCommerce store on the Stores pages, with axe.
- **Live contract checks** on the §2A test store: Step 0, then a repeatable check script.
- All suites pass, with no calls to real merchant sites in CI (except the optional §2A-B job against its own container).

## 15. Tasks (one at a time, report after each)

| Task | Content |
|---|---|
| 2B-01 | Step 0 on a test store (§4.2), depending on §2A |
| 2B-02 | Paged-import framework + migration 0010 (Shopify behaviour unchanged) |
| 2B-03 | Store URL rules, SSRF hardening for merchant hosts, WooCommerce REST client (auth, paging, errors, limiter) |
| 2B-04 | Connect: authorize redirect, key-delivery route, verification, discovery, version check, one-store rule, reconnect |
| 2B-05 | Mapping and initial import (products, variations, stock, cost, orders, refunds; customer data dropped) |
| 2B-06 | 15-minute and nightly checks, deletions, "Sync now", store health |
| 2B-07 | Finance mapping, status and currency rules, parity tests |
| 2B-08 | API additions and web app (connect form, return page, health panel) |
| 2B-09 | Simulator journey, browser test, docs, `PHASE_02B_REPORT.md` |

Estimate: **2–3 weeks** including your reviews; the shared framework from 2A makes this smaller than 2A.

## 16. Acceptance criteria

1. A WooCommerce test store connects, imports, stays up to date and handles disconnect, a revoked key, an unreachable site and reconnect without manual database work.
2. Parity: equivalent Shopify and WooCommerce data give identical daily figures, and figures match WooCommerce Analytics for the Step 0 fixture.
3. No customer name, email, phone or address is stored; credentials never appear in responses, logs, audit or UI.
4. The SSRF suite passes, including rebinding, redirects and private-address cases.
5. Missing data is never shown as 0 (cost when COGS is off, other-currency days, unsynced days).
6. All suites pass, with no calls to real merchant sites in CI.

## 17. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| SSRF through merchant-supplied addresses | **CRITICAL** | §7: one hardened client, DNS check per request, no redirects, extended test suite |
| Hosting differences (security plugins, header stripping, firewalls blocking our server, slow shared hosts) | HIGH | Capability check at connect, health panel with fixes, gentle request rate, back-off |
| Keys never expire and are only revoked by the merchant | MEDIUM | Read-only scope; encrypted; disconnect deletes our copy and asks the merchant to revoke |
| Missing costs (COGS off or older orders) | MEDIUM | "Not available" plus coverage; plugins or manual entry later (your decision) |
| Figures differ from WooCommerce Analytics (custom status settings, date type) | MEDIUM | Step 0 report match; counted statuses shown on the page |
| Multi-currency plugins | MEDIUM | Q-2B-5 rule; Step 0 item 9 |
| Large stores (many orders) | LOW | Paged import resumes; 13-month window; gentle rate |

## 18. Rollback

The migration is additive: downgrade to 0009. The provider can be removed or switched off by configuration. The paged-import step is used only by providers that declare it, so Shopify is unaffected.

## 19. Approval checklist

Approve or change: **Q10a, Q10b, Q-2B-1 … Q-2B-7, the test-environment option (§2A)**, the read-only scope, the finance mapping (§10, to be confirmed in Step 0), and task-by-task delivery 2B-01 … 2B-09. No new runtime packages are proposed.

---

**Sources (verified 2026-10-14):**
- WooCommerce REST API docs: [Authentication](https://developer.woocommerce.com/docs/apis/rest-api/authentication/), [Orders v3](https://developer.woocommerce.com/docs/apis/rest-api/v3/orders/), [Refunds v3](https://developer.woocommerce.com/docs/apis/rest-api/v3/refunds/), [Products v3](https://developer.woocommerce.com/docs/apis/rest-api/v3/products/), [System status v3](https://developer.woocommerce.com/docs/apis/rest-api/v3/system-status/), [Webhooks](https://developer.woocommerce.com/docs/apis/rest-api/v2/webhooks/).
- Cost of goods: [COGS deep-dive (May 2025)](https://developer.woocommerce.com/2025/05/21/cost-of-goods-soldcogs-is-ready-to-blossom-out-of-beta-this-summer/), [WooCommerce 10.3 release](https://developer.woocommerce.com/2025/10/22/woocommerce-10-3-cogs-comes-to-core-and-mcp-beta/), [COGS user guide](https://woocommerce.com/document/woocommerce-cost-of-goods-sold-cogs/).
- Versions: [PHP 8.1 requirement for 11.6](https://developer.woocommerce.com/?p=8771554).
- WordPress REST index: [`WP_REST_Server::get_index`](https://developer.wordpress.org/reference/classes/wp_rest_server/get_index).
- Analytics excluded statuses: [`CustomerHistory::get_excluded_statuses`](https://wp-kama.com/plugin/woocommerce/function/CustomerHistory::get_excluded_statuses).
