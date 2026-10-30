# Phase 2A — Implementation Report (Shopify read-only + finance core)

**Date:** 2026-10-14 · **Branch:** `feature/phase-1a` · **Status:** Implemented against the Shopify simulator — awaiting product-owner review. **Live checks on a Shopify development store (2A-01) are still pending** (option C, A18).
**Plan:** `PHASE_02A_PLAN.md` v2 (approved, A18) · Task-by-task reports: `PHASE_02A_PROGRESS.md` (2A-02 … 2A-11).

---

## 1. Summary

An organization can now connect a Shopify store read-only and see its data. Concretely, it can:

- connect from AdVegaX by typing the store address, or start from a Shopify install link and choose the organization;
- import the catalogue, stock, product costs, orders, sales records and refunds (60 days of history; 13 months once Shopify grants `read_all_orders`);
- keep the data up to date: webhooks within seconds, an hourly check and a nightly deeper check, plus "Sync now";
- see daily store figures (gross sales, discounts, sales reversals, net sales, shipping, taxes, duties, fees, total sales, orders, cost of goods, gross profit and margin, cost coverage), defined like Shopify's own sales reports, in the store's currency and time zone;
- browse products with their stock and cost;
- survive token expiry, disconnect, uninstall, reinstall and store-erasure requests without manual database work.

Two promises hold throughout. **Missing data is never shown as 0**: every figure carries "available", "not available", "not provided by the platform" or "not synced yet" with a reason. **No customer name, email, phone or address is requested or stored.**

All of this is built from Shopify's documentation (verified 2026-10-13) and tested against an in-process **Shopify simulator**. It has **not yet run against a real Shopify store**, because this environment cannot reach Shopify. The live checks list is in §9.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 2A-01 | ⏸ **Deferred:** the live Step 0 on a development store needs network access to Shopify or a staging server (plan §2A) |
| 2A-02 | Commerce data model, migration 0007: 11 tenant tables with forced row-level security and composite keys; a system-only webhook log (no bodies); one live connection per store |
| 2A-03 | Shopify connect, by store address or install link. Checks: HMAC and same-store; expiring tokens; one store per organization, checked **before** the token exchange; reconnect reuses the connection. Shopify simulator added |
| 2A-04 | Token lifecycle: refresh before expiry under a per-store lock, rotated refresh tokens saved, hourly keep-alive, refused refresh → "Needs reconnecting", platform-revocation service |
| 2A-05 | Webhook intake: one signed endpoint, with the CSRF exemption for that path only. HMAC on the raw body, replay window, de-duplication, metadata-only log with 30-day purge. Uninstall → access revoked; privacy requests recorded and audited |
| 2A-06 | Initial import: streaming download with a host allowlist, Shopify bulk exports, normalized records, idempotent upserts (newer wins), cost history, a one-step-at-a-time import chain; migration 0008 |
| 2A-07 | Keeping up to date: webhook → fetch the current object (bursts coalesced, deletions handled), hourly and nightly reconciliation, cost valid at order time, throttling back-off, store erasure carried out; migration 0009 |
| 2A-08 | Finance core v1: daily figures from sales records, using Shopify's report dating and exact decimals. Cost of goods is "not available" when any sold item has no cost, and coverage is shown |
| 2A-09 | Read API: stores with sync status, products with cost and stock availability, daily figures with totals, "Sync now" (rate-limited); store permissions |
| 2A-10 | Web app: Shopify connect form, install-link organization chooser, Stores tab, store page with revenue view and "Sync now", products page |
| 2A-11 | Whole-journey simulator test, strict-token simulator, browser test with an imported store, fix for a date time bomb in the tests, docs, this report |

## 3. Acceptance criteria (plan §16)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Connects from AdVegaX and from an install link, imports, stays in sync, and survives disconnect, uninstall, reinstall and token expiry without manual database work | ✅ with the simulator · ⏸ on a development store | `test_shopify_journey.py` (whole lifecycle with strict tokens), `test_shopify_connect.py`, `test_token_lifecycle.py`, `test_commerce_sync.py`, `test_webhooks.py`; browser: `stores.spec.ts` |
| 2 | Finance figures match hand-calculated golden fixtures to the cent, and match the development store's Sales report | ✅ golden fixtures · ⏸ Sales report | `test_finance_definitions.py`, `test_finance_daily.py`. The Sales-report comparison needs the development store |
| 3 | No customer name, email, phone or address requested or stored; privacy webhooks honoured and audited | ✅ | Bulk and fetch queries request no customer fields (`test_shopify_bulk.py`, `test_commerce_data.py`); `customers/*` and `shop/redact` tests; the journey ends with store erasure |
| 4 | Tokens never in responses, logs, audit, UI or AI context; new routes pass the tenant-isolation and route-guard sweeps | ✅ | Journey: every response, the audit log, webhook records and logs scanned. Browser: page content scanned. Generated sweeps cover every new route. No AI features exist yet |
| 5 | Missing data never shown as 0 (cost, fees, shipping cost, history beyond the allowed window) | ✅ | API tests (not-synchronized days and totals, untracked stock, missing cost); component tests; browser test (no $0.00 for missing values) |
| 6 | All suites pass with no live Shopify calls in CI | ✅ locally · CI on GitHub not yet run | §5. The simulator replaces the network in tests; the browser helper refuses deployed environments |

## 4. Security controls — how each is verified

| Control | Verified by |
|---|---|
| Store address validated (anchored `*.myshopify.com`); the callback must be for the same store; HMAC with the serving app's secret | `test_shopify_connect.py` (tampered, other store, forged install) |
| One live connection per store across organizations, checked before the token exchange | `test_shopify_connect.py` (no exchange happens for the second organization) |
| Tokens encrypted at rest; never in responses, audit, logs or UI | `test_credentials.py`, journey test scan, browser page scan |
| Webhooks: raw-body HMAC, replay window, de-duplication, only metadata stored, CSRF exemption for one path pattern | `test_webhooks.py`, `test_shopify_webhooks.py` |
| Outbound calls only to validated Shopify hosts; downloads only from the allowlisted host, size and time limited | `test_ssrf.py`, `test_shopify_bulk.py` |
| Tenant isolation: forced row-level security on every commerce table; 404 for other organizations' stores | `test_rls.py`, `test_tenant_isolation.py`, `test_commerce_api.py`, browser tenant-boundary test |
| Privacy: no customer PII; customer redaction; store erasure after uninstall | `test_commerce_sync.py`, journey test |
| Test simulator and helper never ship | `backend/tests` excluded from the Docker image; helper refuses staging and production |

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ruff, mypy --strict, **582 passed** (281 at the end of Phase 1), coverage **97 %** |
| Frontend unit/component (Vitest) | **290 passed** (251 at the end of Phase 1), 97.4 % statements; ESLint, Prettier, strict types, API-type drift tests pass; production audit: 0 vulnerabilities; build passes |
| End-to-end + accessibility (Playwright + axe) | **10 passed** (was 9). axe found no serious or critical issues on any page checked, including the new Stores, store revenue and products pages; no security-policy violations or script errors |

## 6. Database

- Migrations **0007** (commerce model, webhook log, daily figures), **0008** (verified Shopify value lists, import fields), **0009** (sync modes).
- Every table has forced row-level security and organization-scoped composite keys. Upgrade and downgrade are tested (`test_migrations.py`).
- Rollback: downgrade to 0006 removes all commerce data. Phase 1 tables are untouched.

## 7. Defects found during Phase 2A (all fixed)

- **2A-07:** the 0008 downgrade's data statements silently touched no rows under forced row-level security. Now wrapped to lift it for one statement.
- **2A-09:** the web app had no message for two webhook error codes added in 2A-05. The reports for 2A-05 to 2A-08 had wrongly said the frontend was unchanged without running its checks. The frontend checks now run for every task.
- **2A-11:** a **date time bomb in the tests**. The sample store's orders have fixed October 2026 dates, while the test clock followed the real date, so several commerce tests would have started failing in December 2026 for no code reason. Found by running the suite with the clock moved; the test clock now starts at a fixed moment.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_02A_PROGRESS.md`. The ones that matter most for review:
1. **Value lists follow Shopify's verified enums** (migration 0008) rather than the plan's draft lists (2A-06).
2. **No hashed customer key and no order country yet.** Whether reading them needs extra Shopify permissions is a live-check question. Until then, new vs returning customers shows "not available" (2A-06).
3. **Refund line items are not imported.** Returns come through sales records, which is what the figures use (2A-06).
4. **One webhook address for all topics**, including privacy topics (2A-05).
5. **Reconciliation reuses the import chain**, and product deletions are detected only by Shopify's delete webhook (2A-07).
6. **Tips and gift cards are excluded from total sales;** adjustments count as reversals. To be confirmed against the live Sales report (2A-08).
7. **"Sync now" is limited per store (6 per hour)**, with 409 for "busy" and "not syncing" (2A-09).
8. **Number and date formats follow the browser language;** the revenue view offers 7, 30 or 90 days (2A-10).
9. **The browser test imports its store through a helper process using the simulator**, not the running worker, so CI never calls Shopify (2A-11).

## 9. Not verified in this environment

- **Anything on real Shopify (2A-01, Step 0).** To confirm on a development store:
  - scope behaviour (incl. customer fields);
  - bulk query shapes and the `ProductSale` fragment;
  - the bulk download host;
  - the `created_at` filter and `Order.updatedAt`;
  - expiring tokens and `read_all_orders` for custom-distribution apps;
  - app-initiated revocation;
  - privacy-webhook headers;
  - live webhook delivery to a public HTTPS address;
  - a Sales-report match for one fixture.

  The full list is in INTEGRATION_GUIDES ("To confirm live").
- **GitHub CI.** It runs on a pull request `feature/phase-1a → main`.
- **Docker image builds.** No Docker daemon is available here; the CI `docker` job builds both images.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| Production distribution: App Store rules (Shopify Billing, embedded app) vs an independent SaaS billed by Stripe | **HIGH** (business) | Q5: develop on development stores, pilot with custom distribution (one app per store), and get Shopify's written answer before launch |
| No live verification yet | **HIGH** (until 2A-01) | Everything was built from documentation; the simulator follows the documented formats. Unknown values are refused rather than guessed, so most live differences would surface as import errors to fix, not as silently wrong numbers |
| Missing product costs in real stores make profit "not available" often | MEDIUM | Cost coverage is shown; manual cost entry could come in a later phase (your decision) |
| `read_all_orders` approval | MEDIUM | 60 days works without it; the UI states the history limit |
| Webhook loss | MEDIUM | Hourly and nightly reconciliation |
| Privacy policy and merchant data-protection agreement | MEDIUM | Needed before any other merchant connects |
| Shopify API version changes (quarterly) | LOW | Pinned `2026-10`; yearly upgrade task with simulator fixture refresh |

## 11. Rollback

- Migrate down to 0006, remove the commerce, finance and webhook domains and the Shopify provider, and remove the Stores pages.
- Phase 1 behaviour is unchanged. The Phase 1 API changes in 2A are additive: connect parameters, the install route and the webhook route.

## 12. Next

1. Product-owner review of this report and `PHASE_02A_PROGRESS.md`.
2. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job.
3. Live checks (2A-01) need a Shopify Partner account, a development store and an app in the Dev Dashboard. They also need either Shopify domains allowed in Claude's network settings plus a tunnel, or a staging server. The app secret stays in a local untracked settings file.
4. Q5 (distribution and billing) needs Shopify Partner Support's written answer before launch.
5. Then Phase 2B (WooCommerce, read-only) after its plan is approved. Its plan can be drafted while the live checks wait.
