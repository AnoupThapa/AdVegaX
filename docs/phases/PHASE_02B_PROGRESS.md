# Phase 2B — Task Reports

Plan: `PHASE_02B_PLAN.md` (approved 2026-10-14, A19, all recommendations). One report per task; `PHASE_02B_REPORT.md` follows task 2B-09.

| Task | Status |
|---|---|
| 2B-01 Step 0 on a local WooCommerce test store | ⏸ Waiting — `wordpress.org` / `downloads.wordpress.org` / `api.wordpress.org` are still blocked by the network settings (checked 2026-10-14) |
| 2B-02 Paged-import framework + migration 0010 | ✅ Done |
| 2B-03 Store URL rules, SSRF hardening, REST client | ✅ Done |
| 2B-04 Connect, key delivery, discovery | ✅ Done |
| 2B-05 Mapping and initial import | ✅ Done |
| 2B-06 Scheduled checks, deletions, Sync now, store health | ✅ Done — awaiting review |
| 2B-07 Finance mapping, status and currency rules, parity tests | Not started |
| 2B-08 API additions and web app | Not started |
| 2B-09 Simulator journey, browser test, docs, report | Not started |

---

## 2B-01 — Step 0 on a local test store (2026-10-14)

**Waiting.** On 2026-10-14 the WordPress download sites (`wordpress.org`, `downloads.wordpress.org`, `api.wordpress.org`) were still blocked by the network settings, so no local WooCommerce store can be installed yet. As agreed in the plan, the work continues against WooCommerce's documentation and a simulator. Every item in plan §4.2 stays "to confirm live", and Step 0 runs as soon as the downloads are allowed.

---

## 2B-02 — Paged-import framework + migration 0010 (2026-10-14)

**Completed**
- **Paged imports, platform-neutral.** A commerce platform now reads its history in one of two ways:
  - **bulk exports** (Shopify, `BULK_IMPORT`, unchanged);
  - **pages** (new `PAGED_IMPORT` capability and `PagedImportProvider` interface). Each job step reads **one page**, applies it, and saves the provider's opaque cursor. A stopped or retried import resumes from the saved page.
- **Shared by both:** the single-chain rule and per-store lock; "newer wins" upserts; link resolution; daily figures; audit; errors; the hourly, nightly and "Sync now" checks.
- **Progress and counts:**
  - the first import's progress moves with the provider's estimate (catalogue up to 40 %, then orders);
  - record counts accumulate over all pages, so the audit shows totals, not the last page.
- **Interfaces:** `CommerceProvider` now holds what every commerce platform has (history limit, fetch by id, webhook topics). Bulk exports moved to `BulkExportProvider`, and the new `PagedImportProvider` reads pages. A provider is used only if it implements what it declares.
- **Migration 0010** (additive). It adds:
  - store fields for self-hosted platforms (address, version, health, counted statuses);
  - `orders.excluded_reason`;
  - the page cursor and running counts on the sync state.

  Up/down/up was checked, and the models match the migrations.
- **New setting:** `COMMERCE_PAGE_INTERVAL` (pause between pages, default none; must not be negative).

**Files changed** (11)
- New (3): `alembic/versions/0010_commerce_self_hosted.py`, `tests/api/test_paged_import.py` (10 tests), this report.
- Modified (8):
  - `app/providers/base/{capabilities,types,interfaces}.py`;
  - `app/domains/commerce/{importer,models}.py`;
  - `app/core/settings.py`;
  - docs `DATABASE_SCHEMA.md`, plan status and status documents.
- Deleted: none.

**Tests**
- **10 new.** The headline test checks parity: the simulator's store, read **page by page** (1, 3 or 100 records per page), ends up **identical** to the bulk import. That covers products, variants and costs, orders, lines and links, sales records, refunds and every daily figure. The others cover:
  - counts accumulating over pages and being audited;
  - the cursor and progress saved between pages, with progress never going backwards;
  - a failed page retried from the same cursor, with nothing duplicated;
  - a permanent error ending the chain and clearing the cursor, and the next start beginning from page one;
  - the hourly check passing "changed since" on every page;
  - a provider that declares paging without implementing it being ignored;
  - the setting refusing negative values.
- **Shopify behaviour is unchanged:** all existing Shopify tests pass untouched.
- **Backend `make check`: 592 passed**, coverage 97 %.
- **Frontend `npm run check`: 290 passed** (no frontend change; the API schema is unchanged).

**Deviations**
1. **Migration 0010 also adds the store health and counted-status fields** that later tasks fill. This keeps the phase to one migration. They stay empty for Shopify.
2. **The `CommerceProvider` interface was split** into a common part plus bulk and paged parts, so WooCommerce does not have to pretend to have bulk exports. This is an internal change; Shopify's code is untouched.

**Blocked:** Step 0 (2B-01) still waits for the WordPress downloads.

**Next task:** 2B-03 — store-address rules, SSRF hardening for merchant hosts, and the WooCommerce REST client (Basic auth, paging, errors, per-store request limit).

---

## 2B-03 — Store addresses, SSRF hardening, WooCommerce REST client (2026-10-14)

**Completed**
- **Store addresses** (`providers/woocommerce/stores.py`). What merchants paste is normalized to `https://host[/sub-folder]`: lower-case host, IDNA, trailing slash and pasted `/wp-admin`, `/wp-json`, `/wp-login.php` tails removed, query and fragment dropped. The following are refused, each with a plain code for the web app:
  - `http://` (`https_required`);
  - user name or password in the address (`credentials_in_url`);
  - any port other than 443;
  - IP addresses in any notation (decimal, octal, hex, IPv6);
  - internal names (`localhost`, `.local`, metadata names);
  - `..` and unsafe path characters;
  - more than 5 path segments;
  - over-long input.
- **REST client** (`providers/woocommerce/client.py`):
  - **HTTP Basic auth only**; the key never goes into a URL;
  - **redirects are never followed** (the store must be addressed exactly, and the key can only reach the stored address);
  - the public WordPress index is read **without** credentials;
  - routes are fixed paths;
  - paging uses `page`/`per_page` (≤ 100) and the `X-WP-Total` / `X-WP-TotalPages` headers.
- **Errors become plain codes:**
  - key refused (`key_rejected` → "Needs reconnecting");
  - host strips the login header (`auth_header_stripped` → fix guide);
  - `permission_denied`, `woocommerce_api_not_found`, `not_found`;
  - `rate_limited` (Retry-After, capped at 5 minutes), retryable server errors;
  - `store_redirected` and `unexpected_response` (e.g. a security plugin's challenge page).

  Response bodies are only read for WooCommerce's fixed error identifier and are never logged or put in errors.
- **Shared outbound client hardening** (all platforms):
  - a **whole-request deadline** (`OUTBOUND_REQUEST_TIMEOUT`, 60 s), so a server dripping its answer slowly cannot hold a worker;
  - callers can choose not to follow redirects.

**Files changed** (12)
- New (4): `app/providers/woocommerce/{__init__,stores,client}.py`; `tests/providers/test_woocommerce_client.py` (74 tests).
- Modified (8):
  - `app/providers/http/{client,policy}.py`, `app/core/settings.py`, `app/runtime.py`;
  - docs `SECURITY.md` §9, `INTEGRATION_GUIDES.md` (new WooCommerce entry), status documents.
- Deleted: none. No migration.

**Tests**
- **74 new.** They cover:
  - address normalization (8 valid forms) and 23 refused forms;
  - Basic auth with the key never in the URL, and requests pinned to the checked address;
  - the index read without credentials;
  - every error mapping, with no body content in errors;
  - Retry-After bounds;
  - redirects to `www.`, another domain or a sub-path: none followed, nothing sent onwards;
  - paging header bounds and fixed routes;
  - **DNS rebinding** (public first, internal on the next request → refused before connecting);
  - store names resolving to loopback, metadata, IPv6 local or CGNAT addresses → never contacted;
  - huge bodies cut off, and a slowly dripping body stopped by the whole-request deadline.
- **Backend `make check`: 658 passed**, coverage 97 % (WooCommerce client 98 %, store addresses 100 %).
- **Frontend `npm run check`: 290 passed** (no frontend change).

**Deviations**
1. **WooCommerce's error identifiers** that tell a rejected key from a stripped header come from its documentation and source naming. They are to be confirmed on the test store (Step 0), and any difference would only change which plain message is shown.
2. **No request limiter inside the client:** the existing per-connection limiter in the job framework applies (each WooCommerce connection is one store). The provider sets a gentle rate (2 requests per second) when it is added in 2B-04.

**Blocked:** Step 0 (2B-01) still waits for the WordPress downloads.

**Next task:** 2B-04 — connect: the authorize redirect, the key-delivery route (single-use, nonce-bound, verified against the stored address), discovery with the version check, the one-store rule and reconnect.

---

## 2B-04 — Connect, key delivery, discovery (2026-10-14)

**Completed**
- **Start:**
  - a manager enters the store address;
  - AdVegaX checks that it answers with a WooCommerce REST API (public index, no credentials);
  - the person is sent to the store's own `/wc-auth/v1/authorize` page asking for **read** access.

  An address that is invalid, unreachable or not WooCommerce is reported before anyone leaves AdVegaX (`STORE_NOT_REACHABLE` with a reason).
- **Key delivery** (new generic route `POST /connections/{provider}/credentials`, server to server):
  - The store posts the generated key. The request needs no session or CSRF; instead it must echo the **single-use connect state**, which is consumed at once.
  - AdVegaX accepts only a **read** key, and only if it works **on the store recorded when the person started**. Nothing in the posted body decides which address is called.
  - WooCommerce must be 9.0 or newer.
  - The person must still be an owner, admin or manager of the organization, and the store must not be connected to another organization.
  - The key is then stored encrypted, and discovery starts.
  - Any failure answers 422 with nothing echoed, so WooCommerce shows the merchant an error.
  - The route is rate-limited per address, limited to 4 KB and exempt from CSRF only for that exact path.
- **The browser's return** goes through the existing callback route. It shows the outcome **once and only to the same signed-in person**: connected, cancelled (the merchant declined; the state is retired so a late delivery fails), or a plain error such as key refused, login header stripped, too old, not read-only, store connected elsewhere, or key never delivered. The web app's existing result handling is reused.
- **Discovery:** one store with its WordPress name, currency and time zone (a named zone, or a whole-hour UTC offset; a fractional offset is left empty rather than guessed).
- **One store, one organization** (the same store under another spelling is recognised); **reconnect reuses** the connection.
- **Disconnect** deletes AdVegaX's copy of the key and calls nothing (a read key cannot revoke itself).
- **WooCommerce is offered only when switched on** (`WOOCOMMERCE_ENABLED`, off by default until Phase 2B is complete).
- **WooCommerce simulator** (`tests/woocommerce_sim.py`): public index, `system_status` with Basic auth, key generation and posting (the merchant's side of the authorize page), and hosting quirks (header stripping, store down, not WooCommerce).

**Files changed** (20)
- New (5): `app/providers/woocommerce/provider.py`, `tests/woocommerce_sim.py`, `tests/api/test_woocommerce_connect.py` (41 tests), `tests/providers/test_woocommerce_provider.py` (20 tests), this report.
- Modified (15):
  - `app/domains/integrations/{service,router,connect_state}.py`, `app/domains/organizations/service.py` (membership check by user id for the server-to-server step);
  - `app/core/security/middleware.py` (second exact exemption), `app/core/settings.py`;
  - `app/providers/base/{capabilities,types,registry}.py`;
  - frontend `lib/api/errors.ts` (messages for the two new error codes);
  - docs `API_SPECIFICATION.md` §5, `SECURITY.md`, `INTEGRATION_GUIDES.md`, status documents.
- Deleted: none. No migration.

**Tests**
- **61 new.** They cover:
  - the full connect with discovery; the key never stored or logged in plain text and verified with Basic auth on the recorded store;
  - invalid and unsafe addresses refused before any call; unreachable and non-WooCommerce stores reported at start; viewers cannot start;
  - a read-write key refused and nothing stored; **a key from another store refused**; too-old versions and header stripping explained;
  - single use, with replays refused; malformed, unknown and oversized deliveries refused with nothing echoed; platforms without key delivery refuse it;
  - the CSRF exemption limited to the exact path; per-address rate limit;
  - declined approvals retire the state; a return without delivery; **another browser cannot read the result**; unknown tokens;
  - one store, one organization (also when another organization finishes first); reconnect reuse; a role lost meanwhile;
  - disconnect deletes the key without calling the store; WooCommerce offered only when switched on; time-zone mapping; provider details.
- **Backend `make check`: 723 passed**, coverage 97 % (WooCommerce provider 97 %, client 98 %, addresses 100 %).
- **Frontend `npm run check`: 290 passed**, build passes. **E2E: 10 passed** (the Phase 1 journey still connects the test platform through the changed callback route).

**Deviations**
1. **The browser returns through the existing API callback**, not a new web-app return page. That reuses the tested result handling, and the single-use state is the same token in both steps. The plan's `/connect/woocommerce/return` page is not needed.
2. **The store's time zone may stay empty** for stores set to a fractional manual UTC offset (e.g. UTC+5:30 without a city). Such a store is connected but not imported until a named time zone is set in WordPress. The store page will say so (2B-06).
3. **`system_status` with a read key** and the exact WooCommerce error identifiers are from the documentation, to be confirmed on the test store (Step 0).

**Blocked:** Step 0 (2B-01) still waits for the WordPress downloads.

**Next task:** 2B-05 — mapping and initial import: products, variations, stock, cost, orders (lines, shipping, fees, taxes, discounts, order-time cost) and refunds, page by page; customer details dropped.

---

## 2B-05 — Mapping and initial import (2026-10-15)

**Completed**
- **WooCommerce is imported page by page** through the 2B-02 framework. Linking a connected store starts the import:
  1. products (all types, by id);
  2. the variations of each variable product;
  3. orders created in the last 13 months (Q-2B-4);
  4. refunds in the same window.

  The cursor, which also carries the store currency read once from the system status, is saved after every page.
- **Catalogue:**
  - a simple product is its own variant;
  - product statuses mapped to the shared ones;
  - stock only when WooCommerce manages it (otherwise "not tracked", never 0);
  - product cost from WooCommerce's cost of goods;
  - the first category as product type.
- **Orders and refunds.** These become the **same kind of sales records as Shopify's**: amount including tax, the tax, and the discount (subtotal − total). The finance core therefore needs nothing WooCommerce-specific, and the sample store produces **the same daily figures as the Shopify sample** (net sales 48.81, total 63.69 on 5 Oct; cost of goods "not available" because the engraving line has no cost).
  - Lines, shipping and fee lines are all mapped.
  - Each refund line is linked to the line it returns.
  - The part of a refund that no line explains becomes a reversal ("adjustment").
- **Costs recorded with the sale:** each order line takes the cost WooCommerce recorded when it was sold. A line without one (sold before cost of goods was switched on) stays **without cost**; it is never given today's product cost (Q-2B-1).
- **Uncounted orders are kept with the reason:** pending payment, failed, cancelled, drafts and trash (Q-2B-2), or another currency (Q-2B-5). Counting them out of the figures is part of 2B-07.
- **Customer details are never stored:**
  - the mapper does not read billing, shipping, email, phone, names or notes;
  - requests ask the store to leave them out (`_fields`);
  - a store that ignores that still leaks nothing.
- **Robustness:**
  - an unreadable record is skipped and counted, never half-stored;
  - the check for changes reads only what was modified;
  - when the per-store request limit is reached, the import **pauses and resumes** instead of failing.
- **Shared framework, small additions:**
  - orders can carry `excluded_reason`;
  - order lines can carry a platform-recorded cost that later product costs never replace.

  Shopify is unchanged.
- **Unrelated fix:** link history ordering had a tie when two links were made at the same moment (an ended link could be listed after the current one). Ended links now come first; this showed up as a flaky test.

**Files changed** (13)
- New (4): `app/providers/woocommerce/mapping.py`, `tests/api/test_woocommerce_import.py` (12 tests), `tests/providers/test_woocommerce_mapping.py` (33 tests), this report.
- Modified (9):
  - `app/providers/woocommerce/provider.py` (paged reader);
  - `app/providers/base/types.py`, `app/domains/commerce/importer.py`, `app/domains/integrations/service.py` (link history order);
  - `tests/woocommerce_sim.py` (paged collections and the sample store);
  - docs `INTEGRATION_GUIDES.md`, status documents.
- Deleted: none. No migration (the columns came with 0010).

**Tests**
- **45 new.** They cover:
  - the full import: products, variants, stock, costs, the order, lines and links, every sales record, the refund, and the daily figures equal to the Shopify sample's;
  - customer details neither requested nor stored, even when the store ignores the field list;
  - many 1-record pages giving the same store (including several variable products and variation pages);
  - the history window with GMT dates;
  - uncounted orders kept with the reason;
  - no cost without cost of goods, even when the product has one;
  - amount-only refunds as reversals;
  - unreadable records skipped and the rest imported;
  - the check for changes reading only modified records;
  - a bad cursor ending the chain;
  - the request limit pausing, not failing;
  - mapping edge cases (money, dates, product types, inherited stock, fees, per-unit cost, which orders count, partly explained refunds).
- **Backend `make check`: 768 passed**, coverage 97 % (WooCommerce provider 97 %, mapping 98 %).
- **Frontend `npm run check`: 290 passed. E2E: 10 passed.**

**Deviations**
1. **Variations changed without their product** (e.g. stock sold) are picked up by the nightly full check, not the 15-minute check. WooCommerce 9.x has no cross-product "changed variations" list. The 10.3+ `/variations` endpoint can speed this up later.
2. **The hashed customer key stays empty** (new vs returning customers "not available"), as for Shopify. It can come later without storing anything personal.
3. **To confirm on the test store (Step 0):**
   - that `cost_of_goods_sold.value` on an order line is the line total (taken as total ÷ quantity);
   - the `/refunds` endpoint and `_refunded_item_id`;
   - that `_fields` is honoured.

**Blocked:** Step 0 (2B-01) still waits for the WordPress downloads.

**Next task:** 2B-06 — the 15-minute and nightly checks for WooCommerce stores, deletions, "Sync now", and store health (unreachable, key refused, header stripped, version, cost of goods off, time zone unknown).

---

## 2B-06 — Scheduled checks, deletions, Sync now, store health (2026-10-15)

**Completed**
- **Checks at each platform's own pace:**
  - the scheduler now looks every 5 minutes and checks each store when it is due;
  - **WooCommerce every 15 minutes** (no webhooks, Q-2B-3);
  - **Shopify hourly as before** (it also has webhooks).
- **Deleted products:**
  - the nightly full check (and "Sync now") reads the whole catalogue;
  - products and variations it no longer lists are **marked deleted** and leave the products page; their order history is kept;
  - the 15-minute checks never delete anything, and an empty catalogue answer (more likely a fault) deletes nothing.
- **"Sync now"** runs that full check for WooCommerce stores, as for Shopify.
- **Daily store health** (with the first import and each nightly check):
  - records the WooCommerce version and the store address;
  - gives one plain warning when something needs the merchant: WooCommerce too old, time zone unknown, or cost of goods switched off;
  - a failed health check never fails the sync.
- **Access problems** use the connection's existing health:
  - a refused key → "Needs reconnecting";
  - a host stripping the login header → an error with that reason;
  - imported data stays readable.
- **A store waiting for a time zone** (2B-04 deviation) starts importing once a rediscovery finds a named time zone. No unlink or relink is needed.
- **Store API:** new optional fields `site_url`, `platform_version`, `health` and `counted_statuses` (processing, on hold, completed, refunded); empty for Shopify. API types regenerated.
- **Undefined costs:** a WooCommerce product with cost of goods on but no cost entered is read as **no cost**, never as a cost of 0 (to confirm live).

**Files changed** (17)
- New (2): `tests/api/test_woocommerce_sync.py` (13 tests), this report.
- Modified (15):
  - `app/domains/commerce/{importer,schemas,read_service}.py`, `app/domains/integrations/jobs.py`;
  - `app/providers/woocommerce/{provider,mapping}.py`, `app/providers/base/{capabilities,types,registry}.py`;
  - `app/core/settings.py`, `app/workers/{celery_app,job_tasks}.py`;
  - `tests/woocommerce_sim.py`, `tests/api/test_commerce_sync.py` (see deviation 1);
  - frontend `lib/api/openapi.json`, `lib/api/schema.d.ts` (regenerated);
  - docs `INTEGRATION_GUIDES.md`, `API_SPECIFICATION.md`, status documents.
- Deleted: none. No migration (the columns came with 0010).

**Tests**
- **13 new.** They cover:
  - WooCommerce due after 15 minutes and Shopify after an hour, side by side;
  - the nightly check marking a deleted product and a deleted variation, with history kept and the 15-minute check never pruning;
  - an empty answer deleting nothing;
  - "Sync now" running the full check;
  - a healthy store's version, address and counted statuses;
  - each configuration warning found by the daily check, with the store still active;
  - change checks not repeating the health check;
  - a failed health check not failing the sync;
  - a revoked key and a stripped header after import;
  - a store waiting for its time zone importing after rediscovery.
- **Backend `make check`: 781 passed**, coverage 97 %.
- **Frontend `npm run check`: 290 passed**, build passes. **E2E: 10 passed.**

**Deviations**
1. **Two existing scheduling tests were updated, not removed.** Before, the scheduler checked every store on every run. Now each store is checked only when its platform's interval has passed. The tests therefore move the clock forward first, and one test now also asserts the new 5-minute scheduler tick.
2. **Configuration warnings are separate from access problems.** The store's health shows only configuration (version, time zone, cost of goods); an unreachable store or refused key shows through the existing connection and sync status, so nothing is reported twice.
3. **Cost of goods "off" is detected from the product data:** WooCommerce sends the cost field only when the feature is on. To confirm live.

**Blocked:** Step 0 (2B-01) still waits for the WordPress downloads.

**Next task:** 2B-07 — finance mapping rules (counting only the counted statuses; other-currency days "not available") and the full parity tests against the Shopify sample.
