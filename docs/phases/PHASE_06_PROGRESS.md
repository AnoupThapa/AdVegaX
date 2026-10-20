# Phase 6 — Progress (unified analytics and financial engine)

Plan: `PHASE_06_PLAN.md` (approved 2026-10-20, A24, all recommendations; completes Q7). One task at a time, a report after each.

| Task | Status |
|---|---|
| 6-01 Step 0: live ECB and NRB feeds | ⏸ Waiting for network access to `data-api.ecb.europa.eu` and `www.nrb.org.np` |
| 6-02 Migration 0016, reporting settings, store assignment | ✅ Done — awaiting review |
| 6-03 Exchange rates: clients, daily job, conversion rules | Not started |
| 6-04 Metric registry `analytics-v1` and its inputs | Not started |
| 6-05 Overview and channels API | Not started |
| 6-06 Campaigns (with GA4 match) and products API | Not started |
| 6-07 Web app: Overview, settings | Not started |
| 6-08 Web app: channels, campaigns, products, "how is this calculated?" | Not started |
| 6-09 Golden datasets, performance check, browser test, `PHASE_06_REPORT.md` | Not started |

## 6-01 — Step 0 (2026-10-20)

**Blocked:** the ECB and Nepal Rastra Bank addresses are not allowed from this environment (the network refuses the connection). Phase 6 is built against recorded copies of their answers; Step 0 checks the live feeds (plan §4.2) once both addresses are allowed in Claude's network settings.

## 6-02 — Migration 0016, reporting settings, store assignment (2026-10-20)

**Completed**
- **Migration 0016** (additive):
  - **`fx_rates`**: published exchange rates, one per source (ECB or Nepal Rastra Bank), currency pair and day, exactly as published, with the source's own unit (NRB quotes JPY per 10 and INR per 100). It is shared reference data, not any organization's: the application can only read it; only the system role (the daily job in 6-03) can write it, and nobody but the migrator can delete from it.
  - **`store_id` on ad accounts and analytics properties** (Q-6-1): which store an account's spend or a property's visits belong to when an organization has several stores. The store must be the organization's own (a composite key enforces it in the database too); removing a store only clears the reference.
- **Store assignment** for owners and admins: `PUT …/ad-accounts/{id}/store` and `PUT …/analytics-properties/{id}/store` with a store or `null` (the whole organization). Recorded in the audit log only when it changes. Managers, analysts and viewers can read the assignment but not change it. Every ad account and property answer now includes `store_id`.
- **Reporting currency and time zone** (Q-6-2) are the organization's existing currency and time zone settings, which owners and admins can already change.

**Files changed** (19)
- New (5): `alembic/versions/0016_unified_analytics.py`, `app/domains/fx/{__init__,models}.py`, `app/domains/metrics/{__init__,assignment}.py`, `tests/api/test_store_assignment.py` (21 tests).
- Modified (14): `app/db/models.py`, `app/domains/advertising/{models,schemas,read_service,router}.py`, `app/domains/analytics/{models,schemas,read_service,router}.py`, `tests/helpers.py` (`put`), `tests/security/test_tenant_isolation.py` (the two new routes are swept), `frontend/lib/api/{openapi.json,schema.d.ts}` (generated), docs `DATABASE_SCHEMA.md` (§13A), `API_SPECIFICATION.md` (§19D), this report, `PROJECT_STATUS.md`.
- Deleted: none.

**Tests**
- **21 new**; the tenant-isolation sweep covers the two new routes.
- **Backend `make check`: 1,509 passed**, coverage 97 %. **Frontend `npm run check`: 387 passed** (types regenerated).

**Security**
- Exchange rates hold no tenant data; the application role cannot write them (tested), the system role cannot delete them (tested).
- Assignments: owners and admins only (tested for manager, analyst, viewer); another organization's store is refused by the API (422) and by the database (tested).

**Migration:** `0016_unified_analytics` — new table `fx_rates`, two nullable columns with foreign keys. Downgrade removes them.

**Deviations**
1. **No `organization_reporting` table** (plan §7): the organization already has a currency and a time zone, chosen when it is created and editable in Settings, so those are the reporting settings. The plan's "defaults to the first store's" becomes "the currency and time zone chosen when the organization was created" — a store in another currency is converted (6-03). Changing it is one setting.

**Blocked:** Step 0 (6-01) — network access to the two rate feeds.

**Next task:** 6-03 — exchange rates: the ECB and Nepal Rastra Bank clients (recorded answers in tests), the daily job, and the one conversion function (each day's rate, the last published rate on weekends and holidays, cross rates through EUR, "not available" without a rate).
