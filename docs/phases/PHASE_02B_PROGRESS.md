# Phase 2B — Task Reports

Plan: `PHASE_02B_PLAN.md` (approved 2026-10-14, A19, all recommendations). One report per task; `PHASE_02B_REPORT.md` follows task 2B-09.

| Task | Status |
|---|---|
| 2B-01 Step 0 on a local WooCommerce test store | ⏸ Waiting — `wordpress.org` / `downloads.wordpress.org` / `api.wordpress.org` are still blocked by the network settings (checked 2026-10-14) |
| 2B-02 Paged-import framework + migration 0010 | ✅ Done — awaiting review |
| 2B-03 Store URL rules, SSRF hardening, REST client | Not started |
| 2B-04 Connect, key delivery, discovery | Not started |
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
