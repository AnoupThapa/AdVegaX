# Phase 2A — Task Reports

Plan: `PHASE_02A_PLAN.md` (approved 2026-10-13, A18, option C: live Shopify checks deferred). One report per task; `PHASE_02A_REPORT.md` follows task 2A-11.

| Task | Status |
|---|---|
| 2A-01 Step 0 on a development store (live) | ⏸ Deferred — needs network access to Shopify or a staging server (plan §2A) |
| 2A-02 Data model and migrations | ✅ Done — awaiting review |
| 2A-03 Shopify connect | ✅ Done — awaiting review |
| 2A-04 Token lifecycle | ✅ Done — awaiting review |
| 2A-05 Webhook intake | ✅ Done — awaiting review |
| 2A-06 HTTP client extensions, GraphQL client, initial import | ✅ Done — awaiting review |
| 2A-07 Webhook processing, incremental sync, reconciliation | ✅ Done — awaiting review |
| 2A-08 Finance core v1 | ✅ Done — awaiting review |
| 2A-09 Read API | ✅ Done — awaiting review |
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


---

## 2A-04 — Token lifecycle (2026-10-13)

**Completed**
- **Refresh before expiry** (`app/domains/integrations/tokens.py`): before any platform call (discovery, sync), the stored access token is refreshed if it expires within `TOKEN_REFRESH_MARGIN` (10 min). Shopify returns a **new refresh token each time**; both new tokens and their expiry times are saved encrypted, and the old ones are discarded.
- **One refresh at a time per store:** refreshes and reconnects of the same platform account share an **account lock** (Redis, expires on its own after 60 s if a worker dies, released only by its owner). Inside the lock the credential row is re-read with a row lock, so a refresh another worker has just done is not repeated. Tested with 4 simultaneous workers → exactly **one** refresh call.
- **Keep-alive:** an hourly scheduled sweep (single instance across workers) refreshes connections whose refresh token has been idle for `TOKEN_KEEPALIVE_INTERVAL` (24 h), so a quiet store never reaches the 90-day expiry. It skips revoked connections and ones that already have a refresh job queued.
- **Refused refresh → "Needs reconnecting":** if the platform rejects the refresh (any 4xx), the connection is marked expired with an audit entry, and the person sees the reconnect prompt. Temporary failures (5xx, timeouts) are retried, not treated as expiry.
- **Reconnect during a refresh:** the reconnect's token exchange waits for the lock; if it is still busy after 15 s the person is told to try again in a moment (`account_busy`) and **no exchange happens**.
- **Revocation by the platform:** `revoke_by_platform()` erases the tokens of every live connection for that platform account, marks it revoked and audits `connection.revoked_by_platform`. Store data is kept. The Shopify uninstall webhook calls it in 2A-05.
- Shopify provider: refresh with `grant_type=refresh_token`; the simulator accepts only the latest refresh token (rotation enforced).

**Files changed** (18)
- New (2): `app/domains/integrations/tokens.py`; `tests/api/test_token_lifecycle.py`.
- Modified (16): `app/core/settings.py`; `app/domains/integrations/{credentials,jobs,service}.py`; `app/providers/base/{capabilities,interfaces}.py`; `app/providers/fake/provider.py`; `app/providers/shopify/provider.py`; `app/workers/{celery_app,job_tasks}.py`; `tests/security/test_static_rules.py`; `tests/shopify_sim.py`; `.env.example`; `docs/SECURITY.md`; `docs/INTEGRATION_GUIDES.md`; `frontend/features/connections/labels.ts`.
- Deleted: none.

**Tests**
- 14 new: refresh before use; no refresh while fresh; refresh job then discovery; rejected refresh → expired + audit; 4 concurrent workers → one refresh; lock exclusive and owner-released; busy reconnect → no exchange; keep-alive sweep and its skips; beat schedule; Shopify rotation; Shopify 400 (expired) vs 503 (retry); uninstall revocation keeps data.
- **Backend `make check`: 385 passed**, coverage 97.5 % (security-critical 99 %); ruff, mypy --strict: pass.
- Frontend: 251 passed, check and build pass; **e2e 9 passed**.

**Security**
- Tokens are decrypted only in the credentials module, the connect service and the new token module (static test enforces this). No token appears in logs, audit, job results or errors.
- Lock release is owner-checked, so a slow worker can never release another's lock.

**Migration:** none.

**Deviations**
1. **Two locks instead of one:** a Redis account lock (across workers and organizations) plus a database row lock (to skip a duplicate refresh). A busy reconnect returns `account_busy` rather than waiting indefinitely.
2. **The credential-boundary static test was changed deliberately:** job-time decryption moved from `jobs.py` to `tokens.py`, which refreshes first.
3. **The local test platform now declares token refresh**, so the shared refresh path is exercised in the e2e journey.
4. **Uninstall handling is a service function now;** the webhook that triggers it is built in 2A-05.

**Blocked:** none. Live confirmation on a development store is still deferred (option C).

**Next task:** 2A-05 — webhook intake: signature check on the raw body, duplicate rejection, metadata-only log, app-uninstalled → revoke, and Shopify's mandatory privacy webhooks.

---

## 2A-05 — Webhook intake (2026-10-13)

**Completed**
- **One webhook address per platform:** `POST /api/v1/webhooks/shopify` receives every Shopify topic, including the three mandatory privacy topics.
- **Checks before anything is stored:**
  - per-IP rate limit;
  - Shopify's **signature over the raw body** (base64 HMAC-SHA256, constant-time), using the store's own app secret first, then a general app; **401 and nothing stored** if it fails;
  - a delivery triggered more than **6 hours** ago, or more than 5 minutes in the future, is refused as a possible replay (Shopify retries for 4 hours, so real retries pass);
  - signed but malformed deliveries get 400; the body-size (1 MB) and JSON-only limits still apply.
- **Browser protections stay on everywhere else:** the request guard skips Origin/CSRF checks only for the exact path `/api/v1/webhooks/<platform>`. Tests prove look-alike paths and all other POSTs are still checked.
- **Metadata only:** webhook id, topic, store, object id, timestamps, organization and status go into `webhook_events`; **the body is discarded** after the ids are read, so customer names, emails, phones and addresses are never stored or logged (tested). Records are deleted after **30 days** by a scheduled purge.
- **Duplicates:** Shopify's webhook id is unique in the log, so a redelivery answers `duplicate` and nothing runs twice.
- **Routing to the organization:** a narrow system lookup — the live connection for the store, otherwise the imported store (privacy requests arrive after uninstall). Unknown stores and topics AdVegaX does not use are recorded as `ignored` and acknowledged.
- **App uninstalled → connection revoked** in a background job: tokens deleted, links ended, audited `connection.revoked_by_platform`; imported data kept. If queuing the job fails, the record is removed so Shopify's retry is handled afresh.
- **Privacy requests** (`customers/data_request`, `customers/redact`, `shop/redact`): recorded and audited as `privacy.request_received` with the organization. Carrying them out is task 2A-07 (Shopify allows 30 days).
- "Object changed" webhooks (products, inventory, orders, refunds, shop, bulk-operation finished) are recorded; fetching the changed objects is 2A-07.

**Files changed** (24)
- New (5): `app/domains/webhooks/{service,router}.py`, `app/providers/shopify/webhooks.py`; tests `tests/api/test_webhooks.py` (28), `tests/providers/test_shopify_webhooks.py` (28).
- Modified (19): `app/core/{errors,settings}.py`, `app/core/security/middleware.py`, `app/api/router.py`; `app/providers/base/{types,interfaces}.py`; `app/providers/{shopify,fake}/provider.py`; `app/domains/integrations/service.py`; `app/workers/{celery_app,job_tasks}.py`; `tests/shopify_sim.py`, `tests/unit/test_settings.py`; `.env.example`; docs `API_SPECIFICATION.md`, `SECURITY.md`, `INTEGRATION_GUIDES.md`; status documents.
- Deleted: none. No frontend change.

**Tests**
- **57 new:** signature (wrong secret, tampered body, missing/garbled header, invalid store header, store-specific secret); topic classification; no customer details in the metadata, the database or the logs; malformed → 400; replay window both ways and 4-hour retries accepted; exemption limited to the exact path; size/type limits; duplicates; ignored stores and topics; uninstall revokes, keeps data, is idempotent and not repeated on redelivery; failed follow-up leaves no record; privacy requests recorded and audited, including `shop/redact` routed through the store after uninstall; purge and its schedule; per-IP limit; settings defaults.
- **Backend `make check`: 442 passed**, coverage 97.6 % (security-critical 99 %, new webhook code 100 %); ruff, mypy --strict: pass.
- Frontend unchanged (251); **e2e 9 passed** against the updated API.

**Security**
- The only CSRF exemption is a fully matched path pattern, authenticated by the platform signature instead.
- No personal data stored; intake log readable by the system role only (2A-02) and purged after 30 days.
- Replay limited by time window plus webhook-id de-duplication.

**Migration:** none (uses `webhook_events` from 0007).

**Deviations**
1. **One endpoint for all topics** (`/webhooks/shopify`) instead of a separate `/webhooks/shopify/compliance` URL. Shopify accepts the same address for privacy topics, and one verified path keeps the CSRF exemption to a single pattern. The route is generic (`/webhooks/{provider}`) for later platforms.
2. **The endpoint is not in the web app's OpenAPI schema** (like the connect callback): it is server-to-server. It is documented in API_SPECIFICATION §20 and covered by its own tests.
3. **Privacy requests are recorded and audited now; carrying them out is in 2A-07**, as planned. For customer requests the Shopify customer id (a number, not personal contact data) is kept in the log so 2A-07 can find that customer's orders; it is deleted with the record after 30 days.
4. **`revoke_by_platform` became a module function** (the service method delegates to it) so the webhook job can call it for one organization.
5. **Webhook subscriptions** (which topics Shopify sends) are configured in the Shopify app settings — set up with the live checks (2A-01).

**Blocked:** none. Live delivery from Shopify needs the public HTTPS address (2A-01, deferred).

**Next task:** 2A-06 — HTTP client extensions, GraphQL client and initial import (products, variants, inventory, last 60 days of orders and refunds) with bulk operations.

---

## 2A-06 — Initial store import (2026-10-13)

Shopify's schema was re-checked against shopify.dev (Admin GraphQL `2026-10`) before writing the import: bulk operations, `Product`, `ProductVariant`, `InventoryItem`, `Order`, `LineItem`, `Refund`, `SalesAgreement`, `Sale` and their enums.

**Completed**
- **Linking a Shopify store now imports it.** The store gets its own record (currency, time zone, history start). The import runs in the background as short steps:
  1. catalogue export: products, variants, price, stock, unit cost;
  2. orders export: orders created in the history window, with their lines, their **sales agreements** (each sale or reversal with its own date), and refunds;
  3. links between rows are tidied up and the store is marked active, with progress shown as 0 → 40 → 100 %.
- **History window:** 60 days by default, which is what Shopify allows without approval. It is 13 months when the store granted `read_all_orders`.
- **Correct "unknown" handling:**
  - Stock is empty (not 0) for untracked items.
  - Cost is empty when Shopify has none or hides it.
  - Order totals that need every line price are left empty if any price is missing.
- **Costs:** Shopify keeps no cost history, so the first import records a cost snapshot. Imported order lines are marked "cost at import". Later imports add a new cost row only when a cost changes. A cost that disappears is recorded as empty from that moment. A cost in a different currency is not recorded (no conversion in 2A).
- **Sales are dated the way Shopify's report dates them:** a refund 3 days after the order is dated on the refund day. Each sale keeps its reason (order / edit / refund / return), its action (order / return / update) and its line type (product, shipping, fee, …).
- **Test orders are excluded.**
- **Re-import is safe:** "Sync now" on a store runs the import again. Nothing is duplicated, and older Shopify data never overwrites newer data.
- **Robust chain:**
  - one step at a time per store;
  - a duplicated job message cannot start a second chain;
  - unlinking or disconnecting stops it;
  - linking again restarts an unfinished import with the same store;
  - an expired download link reruns that export;
  - Shopify refusing the export, a failed export, or the last retry of a temporary error shows as an error on the store, audited as `store.import_failed`.
- **HTTP client extensions:**
  - a **streaming download** that reads line by line with bounded memory and has size, time and per-line limits;
  - a **per-platform host allowlist** for downloads (Shopify: its storage host);
  - no redirects, and no token sent with downloads;
  - the signed download link is never logged or stored.
- **Test platform unaffected:** it has no import capability, so linking its store creates no store record.

**Files changed** (26)
- New (5): `alembic/versions/0008_commerce_import.py`, `app/domains/commerce/importer.py`, `app/providers/shopify/bulk.py`; tests `tests/api/test_commerce_import.py` (20), `tests/providers/test_shopify_bulk.py` (31).
- Modified (21):
  - `app/core/settings.py`, `app/runtime.py`;
  - `app/providers/base/{types,interfaces,capabilities,registry}.py`, `app/providers/http/client.py`, `app/providers/shopify/provider.py`;
  - `app/domains/commerce/models.py`, `app/domains/integrations/{service,jobs,tokens}.py`, `app/domains/jobs/service.py`, `app/workers/job_tasks.py`;
  - `tests/shopify_sim.py`;
  - `.env.example`; docs `DATABASE_SCHEMA.md`, `SECURITY.md`, `INTEGRATION_GUIDES.md`; status documents.
- Deleted: none. No frontend change.

**Tests**
- **51 new:**
  - query limits, and no personal-data fields in any query;
  - operation states;
  - mapping of every value list (unknown values → "other");
  - test-order exclusion; reversal dating; children arriving out of order;
  - malformed lines counted, never guessed;
  - download allowlist, limits, errors and SSRF blocking;
  - end-to-end import through the API; no unknown shown as 0; the cost snapshot and cost changes;
  - idempotent re-import and the newer-wins guard;
  - polling, failure and retry paths; the single-chain guarantees; unlink, disconnect and relink.
- **Backend `make check`: 493 passed**, coverage 96.7 % (security-critical 99 %); ruff, mypy --strict: pass.
- Frontend unchanged (251); **e2e 9 passed**.

**Security**
- Downloads go only to allowlisted hosts, through the SSRF-safe client, with no credentials.
- Signed links are treated as secrets.
- Every write runs under the store's tenant context (RLS).
- No customer data is requested.

**Migration:** `0008_commerce_import` (reversible). It aligns the value lists with Shopify's verified enums, adds `sales_entries.agreement_reason` and `external_line_item_id`, and adds `commerce_sync_state.import_job_id`.

**Deviations**
1. **The value lists changed (migration 0008).** Shopify's verified enums differ from the plan's draft lists:
   - products can be `unlisted`;
   - a sale's action is order / return / update, with the agreement's reason (order, edit, refund, return) stored separately;
   - there is no "tax" line type (taxes belong to each sale), but there are "additional fee" and "adjustment".
2. **No hashed customer key and no order country yet.** Reading them needs `Order.customer` / addresses, and whether that needs extra Shopify permissions is a Step 0 question (2A-01). Both stay empty, which means "not available", until confirmed. New-vs-returning customer figures depend on this.
3. **Refund lines are not imported.** Refund totals are imported, and returned items come through the sales agreements (product, quantity, amount, date), which is what the figures use. `refund_items` stays empty; it can be filled from the refund webhook in 2A-07 if the web app needs it.
4. **Order gross amount** (display only) is the sum of line prices × quantities. It is empty when any line price is missing.
5. **The orders filter uses the creation date** (`created_at`), matching Shopify's 60-day rule. This is to be confirmed live, together with the download host, `Order.updatedAt` and the `ProductSale` fragment inside a bulk query. All are listed under "to confirm live" in INTEGRATION_GUIDES.
6. **Cost-aware rate limiting** (from Shopify's cost reports) remains in 2A-07 as planned. Bulk polling is light: about one call every 30 seconds per store.

**Blocked:** none for the code. A real import needs the live checks (2A-01).

**Next task:** 2A-07 — webhook processing (fetch the changed product/order by id), hourly and nightly reconciliation, cost-aware rate limiting, and carrying out privacy requests (customer and shop erasure).

---

## 2A-07 — Keeping stores up to date (2026-10-13)

**Completed**
- **Webhooks now update data within seconds:**
  - Each Shopify notice only says "this product/order changed". AdVegaX fetches that object's **current** state from Shopify and saves it with the same rules as the import. The notice body is never used as data.
  - A burst of notices for one product becomes **one** fetch.
  - A deleted product is marked deleted; its order history stays.
  - A deleted order is removed with its lines, sales and refunds.
  - A stock change refreshes that product's variants.
  - A refund refetches its order.
  - An object too big for one request is saved as far as fetched, then the store is checked in full by bulk export.
  - Stores still importing, unlinked or disconnected skip notices, and the reason is recorded.
- **Reconciliation, because Shopify doesn't guarantee webhook delivery:**
  - **every hour**, everything changed since the last run (with a 10-minute overlap);
  - **every night**, the whole catalogue plus the last 30 days of orders;
  - **"Sync now"** runs the nightly-style check.
  - These reuse the import chain: one at a time per store, never overlapping a running import. A chain that has been silent for 6 hours is treated as dead and restarted. Scheduled runs don't fill the audit log.
- **Cost at order time:**
  - Orders placed after cost tracking began take the cost valid on the order date ("order time").
  - Older imported orders keep "cost at import".
  - A removed cost means "unknown", never 0.
- **Shopify rate limits:** a throttled request waits as long as Shopify needs to restore the requested query cost (1–60 s), then retries automatically.
- **Privacy requests are carried out:**
  - Customer data request / erasure: AdVegaX holds no customer personal data. This is recorded and audited, and the customer id that came with the request is removed from the log.
  - Store erasure (48 h after uninstall): **every imported row for the store is deleted** and audited with counts. It is skipped (and audited) if the merchant connected the store again.

**Files changed** (25)
- New (6): `alembic/versions/0009_commerce_sync_modes.py`, `app/domains/commerce/{incremental,privacy}.py`, `app/domains/webhooks/events.py`; tests `tests/api/test_commerce_sync.py` (33).
- Modified (19):
  - `app/core/settings.py`;
  - `app/providers/base/{types,interfaces}.py`, `app/providers/shopify/{provider,bulk,webhooks,admin_api}.py`;
  - `app/domains/commerce/{importer,models}.py`, `app/domains/integrations/jobs.py`, `app/domains/webhooks/service.py`, `app/workers/{celery_app,job_tasks}.py`;
  - `alembic/versions/0008_commerce_import.py` (see deviation 3);
  - tests `shopify_sim.py`, `test_webhooks.py`, `test_shopify_webhooks.py`, `test_shopify_bulk.py`, `test_commerce_import.py` (updated for the new behaviour);
  - `.env.example`; docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, `DATABASE_SCHEMA.md`; status documents.
- Deleted: none. No frontend change.

**Tests**
- **33 new:**
  - product, stock, refund and new-order updates;
  - deletions; coalescing; not-found; oversized → reconcile;
  - importing, unlinked and failed cases;
  - hourly and nightly filters; skipping a running chain and restarting a dead one; "Sync now";
  - schedules and their single run per tick;
  - throttle back-off maths;
  - cost-at-order-time rules;
  - store erasure, the reconnected-store skip, and replayed privacy jobs.
- Five 2A-05 webhook tests were updated, because those events are now carried out instead of only recorded.
- **Backend `make check`: 526 passed**, coverage 96.4 % (security-critical 99 %); ruff, mypy --strict: pass.
- Frontend unchanged (251); **e2e 9 passed**.

**Security / privacy**
- Webhook payloads are still discarded at intake; only ids are used.
- Customer ids are removed once a request is handled.
- Store erasure deletes all imported data under the tenant's own context (RLS).
- Every privacy outcome is audited.

**Migration:** `0009_commerce_sync_modes` (reversible). It adds the sync mode and start time.

**Deviations**
1. **Reconciliation reuses the bulk-export import chain** (with update-time filters) instead of a separate sync path. It is one code path with the same safety guarantees.
2. **Missing objects are never deleted on a fetch.** Shopify returns nothing for orders older than 60 days without approval, so "not found" cannot mean "deleted". Deletions come only from the delete topics.
3. **The 0008 migration was corrected.** Its data statements now lift forced row-level security for the one statement, otherwise they would silently touch no rows. This only matters for downgrades with data, but it was found while testing.
4. **Proactive cost budgeting** (slowing down before Shopify throttles) is not added. The back-off on throttling plus the per-connection request limiter keeps single fetches well within limits.
5. **Product deletions are not detected by reconciliation**, only by `products/delete`. Shopify's bulk exports don't list deleted products.

**Blocked:** none for the code. Live checks on a development store are still pending (2A-01).

**Next task:** 2A-08 — Finance core v1: the daily store figures (gross sales, discounts, sales reversals, net sales, shipping, taxes, cost of goods with coverage) built from the sales records, matching Shopify's report dating, never showing unknown values as 0.

---

## 2A-08 — Finance core v1 (2026-10-14)

**Completed**
- **One place where store figures are defined:** `app/domains/finance/definitions.py`, version `finance-v1`. Every stored row records that version. Screens and AI never redefine a figure.
- **Built from Shopify's sales records,** each sale or reversal with its own date, dated the way Shopify's Sales report dates them:
  - an order counts on its order date;
  - a return, cancellation, edit or refunded shipping counts on the day it was processed;
  - days follow the **store's time zone**, including daylight-saving changes;
  - amounts are exact decimals in the store currency, rounded half-even to the currency's cents only when shown.

| Figure | v1 definition (per day) |
|---|---|
| Gross sales | Product lines sold: price × quantity before discounts, excluding tax |
| Discounts | Discounts on those lines (line and order-level shares) |
| Sales reversals | Returns, cancellations, edits and price adjustments (positive = money given back) |
| Net sales | Gross − discounts − reversals |
| Shipping | Shipping charged − shipping discounts − refunded shipping |
| Taxes / duties / fees | As recorded on the sales |
| Total sales | Net + taxes + duties + shipping + fees (Shopify's "Total sales") |
| Orders | Orders placed that day (test orders never imported) |
| Cost of goods | Units × cost valid at order time, minus returned units on the return day. **Empty when any product line of the day has no cost** |
| Cost coverage | Share of net sales whose cost is known |
| Gross profit, margin | Calculated on read, only when every line has a cost; otherwise "Not available" with the reason |
| Shipping cost, payment fees | "Not provided by Shopify": not available, never 0 |
| New vs returning customers | Not available (no customer key yet; see 2A-06 deviation 2) |

- Gift cards (a liability, not a sale) and tips are not counted. Line types Shopify may add in future are not counted but are logged, so they get noticed.
- **The figures stay current:**
  - after an import or the nightly check, the whole window is rebuilt;
  - after the hourly check, only its window;
  - after a webhook, only the days of that order: its order day and every refund/edit day;
  - a deleted order's days are rebuilt without it;
  - store erasure removes the figures along with everything else.
  - Rebuilding is idempotent.

**Found and fixed while testing:** the import built the figures before linking sales to their order lines, so costs looked missing. The order is now link first, then figures, and a test guards it.

**Files changed** (11)
- New (4): `app/domains/finance/{definitions,service}.py`; tests `tests/unit/test_finance_definitions.py` (24), `tests/api/test_finance_daily.py` (8).
- Modified (7): `app/domains/commerce/{importer,incremental}.py`; `tests/api/test_commerce_sync.py` (erasure also removes daily figures); docs `DATABASE_SCHEMA.md`; status documents.
- Deleted: none. No migration (uses `financial_daily` from 0007). No frontend change.

**Tests**
- **32 new.** The **golden tests are hand-calculated to the cent:**
  - line and order discounts; tax-inclusive vs tax-exclusive stores;
  - a partial refund in a later month; a cancelled order; an order edit; a discount removed in an edit;
  - refunded shipping; duties, fees and adjustments; gift cards and tips;
  - missing cost; a cost change mid-period;
  - time-zone day boundaries; Sydney's daylight-saving day (a 23-hour day);
  - orders count; the period summary with availability; display rounding (AUD, USD, JPY, KWD).
- End to end: the imported sample store's two days; idempotent rebuild; refund, new-order and delete webhooks; reconciliation refresh; helpers.
- **Backend `make check`: 558 passed**, coverage 96.5 % (finance code 97–100 %); ruff, mypy --strict: pass.
- Frontend unchanged (251); **e2e 9 passed**.

**Deviations**
1. **Multi-currency presentment:** figures use Shopify's shop-currency amounts only (`shopMoney`). This is covered by the import mapping tests rather than a separate finance fixture.
2. **The "match Shopify's own Sales report" fixture** needs the development store (Step 0, item 5) and stays pending with 2A-01.
3. **Tips and gift cards are excluded** from total sales, and "adjustment" lines count as reversals. Both are to be confirmed against the live Sales report.
4. **Cost of goods for an order-edit price change** (action "update") moves money but not units, so it does not change cost of goods.

**Blocked:** none for the code. Live report comparison is pending (2A-01).

**Next task:** 2A-09 — Read API: stores (sync status, history limit), products (cost and stock availability), daily figures with derived metrics and availability, and "Sync now" (rate-limited).

---

## 2A-09 — Read API (2026-10-14)

**Completed** (documented in API_SPECIFICATION §19A)
- **Stores:**
  - `GET /stores` and `GET /stores/{id}`;
  - status (importing / active / error), linked, connection status;
  - the oldest history Shopify allows;
  - sync state: running, mode, first-import progress, last hourly and nightly checks, last error.
- **Products:**
  - `GET /stores/{id}/products` (title order, cursor paging, search by title or SKU, status filter; deleted products hidden unless asked);
  - `GET …/products/{id}`;
  - every variant shows **stock availability** (untracked is "not available", never 0; tracked 0 is a real 0) and **cost availability** (current cost and source, or why there is none).
- **Daily figures:**
  - `GET /stores/{id}/metrics/daily?from&to`, defaulting to the last 30 store-local days, at most 400;
  - the `finance-v1` components per day, plus cost of goods, gross profit and cost coverage with their availability;
  - totals add margin, shipping cost / payment fees ("not provided by the platform") and new vs returning ("not available");
  - **days without data are "not synchronized", never 0:** before the history start, before the first import has finished, or in the future;
  - when any day of a period is not synchronized, the totals are too, because a partial total would understate.
- **"Sync now":**
  - `POST /stores/{id}/resync` runs a nightly-style check;
  - owner, admin and manager only;
  - limited to 6 per store per hour;
  - "already updating" (409 `SYNC_IN_PROGRESS`) and "not linked / connection inactive" (409 `STORE_NOT_SYNCING`).
- Money is returned as **exact decimal strings** with the currency's minor units, so the web app rounds only for display.
- New permissions: `stores.view` (all members) and `stores.manage` (owner/admin/manager).
- Web app: API types regenerated; friendly messages for the new error codes.

**Files changed** (14)
- New (4): `app/domains/commerce/{router,schemas,read_service}.py`; tests `tests/api/test_commerce_api.py` (19).
- Modified (10):
  - `app/api/router.py`, `app/core/settings.py`, `app/domains/organizations/permissions.py`;
  - `tests/security/test_tenant_isolation.py` (the sweep fills the new `{store_id}` / `{product_id}`);
  - frontend `lib/api/openapi.json`, `lib/api/schema.d.ts` (regenerated), `lib/api/errors.ts`;
  - docs `API_SPECIFICATION.md`; status documents.
- Deleted: none. No migration.

**Tests**
- **19 new:**
  - store list and detail;
  - another organization gets 404 everywhere;
  - products with cost and stock availability; paging, search (a typed `%` is literal), status filter, validation, detail, deleted hidden;
  - daily figures and totals with availability; not-synchronized days and totals; a store still importing; range validation;
  - "Sync now": deep check, rate limit, busy, unlinked; viewers can read but not sync.
- The generated route sweeps cover the new routes: login required, CSRF, malformed ids, other organizations.
- **Backend `make check`: 577 passed**, coverage 96.7 % (new code 98–100 %).
- **Frontend `npm run check`: 251 passed**, build passes; **e2e 9 passed**.

**Correction to earlier reports:** the reports for 2A-05 to 2A-08 said "frontend unchanged (251)" without running the frontend checks. Running them now showed that the web app had no message for two webhook error codes added in 2A-05 (`INVALID_SIGNATURE`, `INVALID_WEBHOOK`). They are added here. I now run the frontend checks for every task.

**Deviations**
1. **Errors use 409 for "busy" / "not syncing"** and 429 for the rate limit, following the existing conventions. The plan named no codes.
2. **"Sync now" is limited per store, not per person**, because each run is a full check of the store.

**Blocked:** none.

**Next task:** 2A-10 — Web app: Shopify connect form and "Choose organization" page for install links, stores list with sync status, products page, store revenue view with availability, and "Sync now".
