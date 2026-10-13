# Phase 2A — Task Reports

Plan: `PHASE_02A_PLAN.md` (approved 2026-10-13, A18, option C: live Shopify checks deferred). One report per task; `PHASE_02A_REPORT.md` follows task 2A-11.

| Task | Status |
|---|---|
| 2A-01 Step 0 on a development store (live) | ⏸ Deferred — needs network access to Shopify or a staging server (plan §2A) |
| 2A-02 Data model and migrations | ✅ Done — awaiting review |
| 2A-03 Shopify connect | Not started |
| 2A-04 Token lifecycle | Not started |
| 2A-05 Webhook intake | Not started |
| 2A-06 HTTP client extensions, GraphQL client, initial import | Not started |
| 2A-07 Webhook processing, incremental sync, reconciliation | Not started |
| 2A-08 Finance core v1 | Not started |
| 2A-09 Read API | Not started |
| 2A-10 Web app | Not started |
| 2A-11 Simulator, e2e, docs, report | Not started |

---

## 2A-02 — Data model and migrations (2026-10-13)

**Completed**
- **Migration `0007_commerce`** (upgrade → downgrade → upgrade verified; models match the migration):
  - 11 platform-neutral **tenant tables**: `stores`, `products`, `product_variants`, `product_cost_history`, `orders`, `order_items`, `sales_entries`, `refunds`, `refund_items`, `commerce_sync_state`, `financial_daily`.
    - Row-Level Security enabled and forced.
    - Composite tenant foreign keys on every parent reference, so a row can never point at another organization's data, even when security is bypassed.
    - App-role policies for read, insert, update **and delete**. Delete is needed for privacy erasure requests and re-imports, and is still limited to the organization's own rows.
  - **`webhook_events`**: the webhook intake log.
    - Only the system role can read or write it; the app role has no access.
    - It stores **metadata only**. There is no column for the request body, so personal data in Shopify payloads can never be stored (Q8).
    - Duplicate deliveries are rejected by a unique webhook id.
  - **`external_connections.external_account_id`**: a cross-organization rule that allows **one live connection per platform account** (Q6). A revoked connection frees the account.
  - **Narrow system-role read access**:
    - `stores`, to route a webhook to its store.
    - `external_connections`, to check before a token exchange whether the store is already connected elsewhere.
    - The system role still cannot read orders, products or figures.
- **Integrity rules in the database:**
  - Money is exact (`NUMERIC(20,6)`).
  - A day's cost of goods must be **empty (not 0) exactly when some lines have no cost**.
  - An order line's cost and its source are both set or both empty.
  - Deleting a product that has orders is refused, so order history is never lost.
  - Deleting a store removes all of its data. That is what a Shopify `shop/redact` erasure will use.
- **Models:**
  - New: `app/domains/commerce/models.py`, `app/domains/webhooks/models.py`, `app/domains/finance/models.py`.
  - Changed: `ExternalConnection` gains `external_account_id`.
  - `app/db/models.py` now imports every model, including the Phase 1B models it previously left out.
- **DATABASE_SCHEMA.md:** new §4A describes the tables as built; the old target sections point to it.

**Files changed** (9)
- New (6): `backend/alembic/versions/0007_commerce.py`; `app/domains/{commerce,webhooks,finance}/models.py` (+ `__init__.py`); `tests/security/test_commerce_data.py`.
- Modified (3): `app/domains/integrations/models.py`, `app/db/models.py`, `docs/DATABASE_SCHEMA.md`.
- Deleted: none. No API or frontend change.

**Tests**
- 16 new tests, run as the real runtime roles:
  - Each organization sees only its own commerce rows.
  - Nothing is visible without an organization context.
  - Another organization's rows can't be updated, deleted or inserted.
  - Composite keys block cross-organization references for orders, order lines, line variants, costs and refund lines.
  - Money is exact.
  - The "cost empty, never 0" rule holds.
  - Order history survives an attempt to delete a variant.
  - Store erasure removes everything for that store, and the other organization's data is untouched.
  - One live connection per account across organizations, and a revoked connection frees the account.
  - The system role's access is narrow.
  - The webhook log is system-only, de-duplicated, and has no body column.
- **Backend `make check`: 297 passed** (+16), coverage 98.50 % (security-critical 99 %); ruff, mypy --strict: pass.
- Frontend: 251 passed (unchanged; no API change).

**Security**
- New tables follow the 1A/1B isolation pattern. Three changes are deliberate and tested:
  - The app role can now delete, limited to its own tenant.
  - The system role has two read-only grants.
  - The webhook log is inaccessible to the app role.
- No personal-data columns exist anywhere. The customer key is a one-way hash, filled in later in 2A-06.

**Migration:** `0007_commerce` (reversible).

**Deviations from the plan**
1. **Inventory is stored on `product_variants`** (summed available quantity, tracked flag, sync time) rather than a separate `inventory_levels` table. AdVegaX needs only the total per variant, so a second table would add joins without benefit.
2. **`financial_daily` holds the store components only.** Ad-spend components (DATABASE_SCHEMA's original list) are added in Phase 6, when ad spend exists.
3. **`app/db/models.py`** now imports the Phase 1B models too, so the model registry is complete in every process (no behaviour change).

**Blocked:** none for this task. The live Step 0 checks (2A-01) remain deferred (option C).

**Next task:** 2A-03 — Shopify connect. It covers:
- the store-address start;
- the Shopify-initiated install;
- callback checks (HMAC, shop, state);
- expiring tokens;
- the one-store check before the token exchange;
- reconnecting without duplicating data.

All of it is built against Shopify's documented formats and tested with recorded responses.
