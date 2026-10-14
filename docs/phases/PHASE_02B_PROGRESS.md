# Phase 2B — Task Reports

Plan: `PHASE_02B_PLAN.md` (approved 2026-10-14, A19, all recommendations). One report per task; `PHASE_02B_REPORT.md` follows task 2B-09.

| Task | Status |
|---|---|
| 2B-01 Step 0 on a local WooCommerce test store | ⏸ Waiting — `wordpress.org` / `downloads.wordpress.org` / `api.wordpress.org` are still blocked by the network settings (checked 2026-10-14) |
| 2B-02 Paged-import framework + migration 0010 | ✅ Done |
| 2B-03 Store URL rules, SSRF hardening, REST client | ✅ Done |
| 2B-04 Connect, key delivery, discovery | ✅ Done — awaiting review |
| 2B-05 Mapping and initial import | Not started |
| 2B-06 Scheduled checks, deletions, Sync now, store health | Not started |
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
