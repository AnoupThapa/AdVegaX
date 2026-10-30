# Phase 2B — Implementation Report (WooCommerce read-only)

**Date:** 2026-10-15 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the WooCommerce simulator — awaiting product-owner review. **Live checks on a WooCommerce test store (2B-01, Step 0) are still pending**: the WordPress download sites are blocked by this environment's network settings.
**Plan:** `PHASE_02B_PLAN.md` (approved 2026-10-14, A19, all recommendations) · Task-by-task reports: `PHASE_02B_PROGRESS.md` (2B-02 … 2B-09).

---

## 1. Summary

An organization can now connect a WooCommerce store read-only, next to Shopify, and see the same kind of data. Concretely, it can:

- connect by typing the store's web address. WordPress in a sub-folder works, and HTTPS is required. The merchant approves **read-only** access on the store's own WordPress page, and the store sends the key straight to AdVegaX's server;
- import the catalogue, variations, stock, product costs, orders and refunds (13 months of history), page by page and resumable;
- keep the data up to date: a change check every 15 minutes, a nightly full check that also finds deleted products, and "Sync now";
- see the **same daily store figures as for Shopify**. The two sample stores give identical figures to the cent;
- see what needs attention in plain words: WooCommerce too old, time zone not set, cost of goods switched off, key refused, web host stripping the login header;
- recover from a revoked key and reconnect, and disconnect, without manual database work.

Three promises hold throughout:

- **Missing data is never shown as 0.** This covers cost when cost of goods is off, days with orders in another currency, and days not synced yet.
- **No customer name, email, phone or address is stored.** Customer details are not requested either, where the store honours the field list.
- **The store key is never shown.** It never appears in a response, the audit log, the logs or the web app.

Everything is built from WooCommerce's documentation (verified 2026-10-14) and tested against an in-process **WooCommerce simulator**. It has **not yet run against a real WooCommerce store**. The live checks are listed in §9.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 2B-01 | ⏸ **Waiting:** Step 0 on a local test store needs `wordpress.org`, `downloads.wordpress.org` and `api.wordpress.org` allowed in Claude's network settings |
| 2B-02 | Paged-import framework: one page per job step, a resumable cursor, and the same locks, upserts and figures as Shopify's bulk import. Migration 0010 adds the self-hosted store fields, the reason an order is not counted, and the page cursor. Shopify is unchanged |
| 2B-03 | Store-address rules (HTTPS, public names, safe sub-folders) and hardening against requests being steered to private networks (SSRF): DNS checked per request, no redirects followed. Also a WooCommerce REST client (Basic auth, keys never in URLs, plain error codes, paging) and a whole-request deadline for every outbound call |
| 2B-04 | Connect: the address is checked first; the store's own approval page; server-to-server key delivery (single-use, read keys only, verified on the recorded store, WooCommerce ≥ 9.0); the result shown once to the same person; discovery; one store per organization; reconnect reuses the connection; offered only when switched on |
| 2B-05 | Mapping and import: products, variations, stock, costs (order-time cost per line), orders with shipping and fees, and refunds, as the same sales records as Shopify. Uncounted orders are kept with the reason; customer details are dropped; the import pauses at the request limit |
| 2B-06 | Each store is checked at its platform's pace (WooCommerce every 15 minutes, Shopify hourly). The nightly check marks deleted products and variations and keeps the history. Daily store health; stores waiting for a time zone start once it is set |
| 2B-07 | Finance rules: only counted orders are in the figures, and a status change rebuilds the order day. Orders in another currency are never summed; their days and period totals show "Not available — orders in other currencies". Shopify/WooCommerce parity to the cent. Migration 0011 |
| 2B-08 | Web app: store-address form with plain reasons, approval note, plain connect and sync messages, store health panel with fixes, counted-orders note, version and address, cost hint on the products page, revoke-key note on disconnect |
| 2B-09 | Whole-journey simulator test, browser test with a simulated WooCommerce store and accessibility checks, browser-test helper, docs, this report |

## 3. Acceptance criteria (plan §16)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | A WooCommerce test store connects, imports, stays up to date and handles disconnect, a revoked key, an unreachable site and reconnect without manual database work | ✅ with the simulator · ⏸ on a test store | `test_woocommerce_journey.py` (connect → import → 15-minute changes → refund → paid order → key revoked → reconnect → health → disconnect), `test_woocommerce_connect.py`, `test_woocommerce_sync.py`, `test_woocommerce_import.py`; browser: `woocommerce.spec.ts` |
| 2 | Equivalent Shopify and WooCommerce data give identical daily figures, and match WooCommerce Analytics for the Step 0 fixture | ✅ parity · ⏸ Analytics match | `test_woocommerce_finance.py` (API figures and stored rows identical to the cent; 2A golden values). The Analytics comparison needs the test store |
| 3 | No customer name, email, phone or address stored; credentials never in responses, logs, audit or UI | ✅ | The simulator sends full billing and shipping details on purpose. The journey test scans every response, the audit log, the stored orders and the logs for them and for the key and secret. The browser test scans the page. `test_woocommerce_import.py` covers a store that ignores the field list |
| 4 | The SSRF suite passes, including rebinding, redirects and private-address cases | ✅ | `test_woocommerce_client.py` (74 tests), `test_ssrf.py` |
| 5 | Missing data never shown as 0 (cost when COGS is off, other-currency days, unsynced days) | ✅ | `test_woocommerce_finance.py`, `test_woocommerce_sync.py`, component tests, browser test (no $0.00, cost hint) |
| 6 | All suites pass, with no calls to real merchant sites in CI | ✅ locally · CI on GitHub not yet run | §5. The simulator replaces the network; the browser helper refuses deployed environments; the browser test never submits a usable address |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Store address: HTTPS, public DNS name, port 443, safe sub-folder, no user name or password | `test_woocommerce_client.py`, `test_woocommerce_connect.py`; the browser-side check is a convenience only |
| SSRF: every request resolves and checks the address; private, internal and rebinding answers are refused; no redirects; whole-request deadline; size limits | `test_woocommerce_client.py`, `test_ssrf.py` |
| Key delivery: exact CSRF-exempt path, JSON only, at most 4 KB, rate-limited per IP; single-use state; read keys only; the key is verified on the store recorded at start (the posted body never decides which store is called) | `test_woocommerce_connect.py` (incl. that every other POST still needs a session and CSRF) |
| Keys encrypted at rest; never in responses, audit, logs or UI; disconnect deletes the stored key | `test_credentials.py`, journey scan, browser page scan |
| One live connection per store across organizations; a person who lost the role cannot finish connecting | `test_woocommerce_connect.py` |
| Tenant isolation: forced row-level security; every new query is store-scoped | `test_rls.py`, `test_tenant_isolation.py`, generated route sweeps |
| Customer details never stored | Mapper drops them; journey and import tests scan for them |
| Test simulator and helpers never ship | `backend/tests` excluded from the Docker image; helpers refuse staging and production |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ruff, mypy --strict, **799 passed** (582 at the end of Phase 2A), coverage **97 %** |
| Frontend unit/component (Vitest) | **343 passed** (290 at the end of Phase 2A); ESLint, Prettier, strict types and API-type drift tests pass; production audit 0 vulnerabilities; build passes |
| End-to-end + accessibility (Playwright + axe) | **11 passed** (was 10). No serious or critical accessibility issues on any page checked, including the WooCommerce connect form, store page and products page; no security-policy violations or script errors |

## 6. Database

- **0010** (self-hosted store fields, `orders.excluded_reason`, paged-import cursor) and **0011** (`financial_daily.other_currency_orders`). Both are additive only.
- Upgrade and downgrade are tested (`test_migrations.py`). Rollback: downgrade to 0009 removes them; Shopify data is untouched.

## 7. Defects found during Phase 2B (all fixed)

- **2B-05:** the order of a connection's link history could change between runs when two links had the same time. A tie-breaker was added.
- **2B-07:** a change check rebuilt figures only from its own start time. **An older order whose status changed** (pending → processing, or a cancellation) left its order day stale. Each check now also rebuilds the earlier days of the orders it changed. This also applies to Shopify.
- **2B-07:** the revenue page would have labelled other-currency days "Not synced yet". It now says why figures are missing.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_02B_PROGRESS.md`. The ones that matter most for review:

1. **One extra migration (0011)** for other-currency days, so later phases reusing the daily figures see them too (2B-07).
2. **No separate return page.** The browser comes back through the existing connect callback, which shows the result once on the Connections page, as for Shopify (2B-04, 2B-08).
3. **The provider interface was split** into common, bulk and paged parts (internal; Shopify unchanged) (2B-02).
4. **Variations changed without their product** (e.g. stock sold) are picked up by the nightly check, not the 15-minute check. WooCommerce 9.x has no cross-product list of changed variations (2B-05).
5. **A store with a fractional manual UTC offset** (e.g. UTC+5:30 without a city) is connected but not imported until a named time zone is set. The store page explains it (2B-04, 2B-06).
6. **Configuration warnings are separate from access problems:** health shows configuration only, and access problems show through the connection status (2B-06).
7. **The browser test imports its store through a helper process with the simulator.** The CI browser job switches WooCommerce on only to show the form (2B-09).

## 9. Not verified in this environment

- **Anything on a real WooCommerce store (2B-01, Step 0, plan §4.2).** To confirm on the test store:
  - the callback rules and the key's fate if our callback fails;
  - a read key on `system_status`;
  - `_fields` on orders and refunds;
  - the maximum `per_page` and the paging headers;
  - whether line totals ever include tax;
  - amount-only refunds;
  - the cost fields with COGS on and off (and line cost = line total);
  - `modified_after` catching status, refund and stock changes;
  - a multi-currency plugin's orders;
  - the exact error identifiers (rejected key vs stripped header);
  - the WordPress menu paths in the hints;
  - **a match with WooCommerce Analytics → Revenue for a fixed set of orders.**
- **GitHub CI.** It runs on a pull request `feature/phase-1a → main`.
- **Docker image builds.** No Docker daemon is available here; the CI `docker` job builds both images.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| No live verification yet | **HIGH** (until Step 0) | Built from documentation; unknown values are refused rather than guessed, so live differences would show as import errors to fix, not silently wrong numbers |
| Hosting differences (security plugins, firewalls, header stripping, slow shared hosts) | HIGH | Address checked at connect; plain health messages with fixes; 2 requests per second per store; back-off |
| Keys do not expire and only the merchant can revoke them | MEDIUM | Read-only; encrypted; disconnect deletes our copy and asks the merchant to revoke it in WordPress |
| Missing costs (COGS off, or orders from before it was on) | MEDIUM | "Not available" plus cost coverage; manual cost entry later (your decision) |
| Figures differing from WooCommerce Analytics (status settings, date basis) | MEDIUM | Step 0 match; counted statuses shown on the store page |
| Multi-currency plugins | MEDIUM | Those days are "not available" until currency conversion (Phase 6) |
| New vs returning customers | LOW | "Not available", as for Shopify, until a hashed customer key is collected |

## 11. Rollback

- Switch WooCommerce off (`WOOCOMMERCE_ENABLED=false`, the default) to stop offering it.
- For a full removal: migrate down to 0009 and remove the WooCommerce provider and its web-app wording.
- The paged-import step is used only by providers that declare it, so Shopify is unaffected. The 2B-07 rebuild fix is harmless to keep.

## 12. Next

1. Product-owner review of this report and `PHASE_02B_PROGRESS.md`.
2. Allow `wordpress.org`, `downloads.wordpress.org` and `api.wordpress.org` in Claude's network settings. I then run Step 0 on a local WooCommerce test store, including the Analytics match, and fix any differences.
3. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job.
4. Shopify live checks (2A-01) remain pending; they need the Shopify Partner account, development store and app.
5. Then Phase 3 (Google Ads, read-only). Its plan can be drafted while the live checks wait. The Google Ads developer-token application should start early.
