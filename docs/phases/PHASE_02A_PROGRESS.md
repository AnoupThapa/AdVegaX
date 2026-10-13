# Phase 2A — Task Reports

Plan: `PHASE_02A_PLAN.md` (approved 2026-10-13, A18, option C: live Shopify checks deferred). One report per task; `PHASE_02A_REPORT.md` follows task 2A-11.

| Task | Status |
|---|---|
| 2A-01 Step 0 on a development store (live) | ⏸ Deferred — needs network access to Shopify or a staging server (plan §2A) |
| 2A-02 Data model and migrations | ✅ Done — awaiting review |
| 2A-03 Shopify connect | ✅ Done — awaiting review |
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

---

## 2A-03 — Shopify connect (2026-10-13)

**Completed**
- **Shopify provider** (`app/providers/shopify/`): read-only, GraphQL Admin API `2026-10`.
  - **Connect from AdVegaX:** the person enters the store address. A bare name, `name.myshopify.com` or a pasted store URL all work. The app then goes to Shopify's approval page with read-only permissions: products, inventory and orders.
  - **Shopify's reply is checked before anything happens:**
    - its **signature** (HMAC, compared in constant time) using that store's app secret;
    - that it is about **the same store** the person started with (the store is kept on the server, never trusted from the browser);
    - that **all needed permissions were approved**.
  - **Expiring tokens** (`expiring=1`, required for new Shopify apps): access token valid 1 hour, refresh token 90 days. Both are stored encrypted with their expiry times. Refreshing them is the next task (2A-04).
  - **Store discovery:** finds exactly one store, with name, currency and time zone. It refuses a token that answers for a different store.
  - **Connect from Shopify (install link):** Shopify's signature and a 5-minute freshness limit are checked. Nothing is stored at this point: the browser is sent to the web app, where the person signs in and chooses the organization. That screen comes in 2A-10.
  - **Several Shopify apps:** one per merchant, as custom distribution requires. Each app lists which stores it serves.
  - Shopify is only offered when an app is configured. Secrets come from settings only, are hidden from logs and never go in a URL.
- **One store, one organization (Q6):**
  - Checked when connecting starts and again **before the token exchange**. Exchanging would retire the other organization's token at Shopify.
  - The database rule from 2A-02 catches a simultaneous attempt by two organizations.
  - The person sees: "This account is already connected to another AdVegaX organization…"
- **Reconnecting keeps everything:** the same organization reconnecting the same store reuses its connection, store and links. This also works after a disconnect. It is audited as `connection.reconnected`.
- **Framework (additive; the test platform is unchanged):**
  - The start request takes optional connect details.
  - The connect state carries those details on the server only.
  - Providers get two new steps: validating connect details and verifying an install.
  - Stored credentials are now updated on reconnect, and the refresh-token expiry is recorded.
- **Web app:** messages for the new error codes. The Shopify connect form and the "Choose organization" page come in 2A-10.
- **Shopify simulator for tests** (`tests/shopify_sim.py`): speaks Shopify's documented token and GraphQL formats behind the real safe HTTP client and records every request. No network is used.

**Files changed** (30, plus status documents)
- New (6):
  - `app/providers/shopify/` — `__init__.py`, `config.py`, `shops.py`, `signatures.py`, `admin_api.py`, `provider.py`.
  - Tests are listed separately below.
- Modified (21):
  - `app/core/settings.py` (Shopify settings), `app/runtime.py`.
  - `app/providers/base/` — `types.py`, `interfaces.py`, `capabilities.py`, `errors.py`, `registry.py`; `app/providers/fake/provider.py`.
  - `app/domains/integrations/` — `service.py`, `router.py`, `schemas.py`, `connect_state.py`, `credentials.py`.
  - `.env.example`; docs: `API_SPECIFICATION.md`, `INTEGRATION_GUIDES.md`, `SECURITY.md`.
  - Frontend: `lib/api/openapi.json` and `schema.d.ts` (regenerated), `lib/api/errors.ts`, `features/connections/labels.ts`.
- Tests (3 new): `tests/shopify_sim.py`, `tests/providers/test_shopify.py` (49), `tests/api/test_shopify_connect.py` (25).
- Deleted: none. No migration.

**Tests**
- **74 new tests**, including:
  - store-address rules, including `shop.myshopify.com.attacker.example`;
  - the signature algorithm;
  - configuration parsing that never echoes secrets;
  - the authorization address (read-only permissions, secret never in the URL);
  - token exchange (form body, `expiring=1`);
  - tampered callback, wrong store and too few permissions: **no token exchange happens**;
  - token-endpoint and GraphQL errors normalized without echoing response bodies;
  - install signature and freshness;
  - the full API flow through the real database and job runner;
  - viewers refused;
  - a second organization refused at start, refused **before the exchange** when both started together, and refused by the database in a race;
  - reconnect reuses the connection and keeps links, also after a disconnect;
  - a disconnected store can move to another organization;
  - audit entries, with no tokens in audit or logs;
  - the test platform still refuses connect details;
  - Shopify is offered only when configured, and bad configuration fails at startup.
- **Backend `make check`: 371 passed**, coverage 97.7 % (security-critical 99 %); ruff, mypy --strict: pass.
- Frontend: 251 passed, check and build pass; **e2e 9 passed** (test-platform journey unchanged).

**Security**
- No secrets in URLs, logs, audit or responses.
- Every Shopify request is signature-checked before any action.
- Install requests are replay-limited.
- Shopify hosts are restricted to validated `*.myshopify.com` names, through the SSRF-safe client.
- The cross-organization check uses a narrow, read-only system lookup.

**Migration:** none (uses 0007 from 2A-02).

**Deviations**
1. **The install route is a generic `GET /connections/{provider}/install`** rather than Shopify-only, so a future platform with installs reuses it. Platforms that don't declare the capability answer `unsupported`.
2. **Shopify does not use PKCE.** The CSRF protection for the flow is the single-use server-side state plus Shopify's HMAC.
3. **Disconnect** deletes AdVegaX's tokens but cannot revoke them at Shopify: no app-initiated revocation is documented for this flow (to confirm live). The web app will tell the person to also uninstall the app in Shopify (2A-10).
4. **Configuration is validated when the provider registry is built** (at startup), not in the settings module. This keeps platform code out of the core (architecture rule D19, caught by the static test).

**Blocked:** none. Live confirmation on a development store is still deferred (option C).

**Next task:** 2A-04 — token lifecycle: refresh before expiry with a per-store lock, rotation, keeping the 90-day refresh token alive, failure → "Needs reconnecting", and disconnect/uninstall handling.

