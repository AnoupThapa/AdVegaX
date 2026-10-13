# Phase 2A — Task Reports

Plan: `PHASE_02A_PLAN.md` (approved 2026-10-13, A18, option C: live Shopify checks deferred). One report per task; `PHASE_02A_REPORT.md` follows task 2A-11.

| Task | Status |
|---|---|
| 2A-01 Step 0 on a development store (live) | ⏸ Deferred — needs network access to Shopify or a staging server (plan §2A) |
| 2A-02 Data model and migrations | ✅ Done — awaiting review |
| 2A-03 Shopify connect | ✅ Done — awaiting review |
| 2A-04 Token lifecycle | ✅ Done — awaiting review |
| 2A-05 Webhook intake | ✅ Done — awaiting review |
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
