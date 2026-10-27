# AdVegaX — API Specification

> **Amended 2026-10-08** for decisions D1–D22 (MASTER_SPECIFICATION.md §20) and Phase 0 approvals A1–A14 (§21). Endpoints are implemented in the phase that introduces their functionality.

## 1. API Principles

Base path:
`/api/v1`

All APIs must:
- authenticate where required,
- authorize organization/resource access,
- validate inputs,
- return stable schemas,
- use consistent errors,
- emit correlation IDs,
- enforce tenant scope.

API host, allowed origins and OAuth callback URLs are environment-configured (Decision D13). CORS uses an explicit allowlist with credentials; `*` is never used for authenticated production requests.

## 2. Standard Response

Success:
```json
{
  "data": {},
  "meta": {
    "request_id": "..."
  }
}
```

List:
```json
{
  "data": [],
  "meta": {
    "request_id": "...",
    "page": 1,
    "page_size": 50,
    "total": 0
  }
}
```

Error:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": []
  },
  "meta": {
    "request_id": "..."
  }
}
```

Do not expose stack traces.

### Metric values and data availability (A5, A10)

Any metric that a provider may not supply is returned as an object, never as a bare number that could silently be 0:

```json
{
  "value": "1234.50",
  "currency": "AUD",
  "availability": "available",
  "sources": ["shopify"],
  "as_of": "2026-10-08T00:00:00Z",
  "definition_version": "finance-v1"
}
```

- `availability` ∈ `available`, `unavailable`, `unsupported`, `not_synchronized`; when not `available`, `value` is `null`.
- Money and ratios are serialized as decimal strings.
- Derived metrics (ROAS, CPA, CTR, CPC, conversion rate, margins, budget utilization) are computed by the backend from stored components; clients never compute them.

## 3. Authentication (Phase 1A)

First version: email + password with email verification (A8). Every state-changing request requires a valid CSRF token; responses for unknown emails are indistinguishable from known ones.

### GET /auth/csrf
Issues/returns the CSRF token for the current browser session.

### POST /auth/register
Creates a user and password credential; sends a verification email. Does not reveal whether the email already exists.

### POST /auth/verify-email
Consumes a single-use verification token.

### POST /auth/resend-verification
Re-sends verification (throttled).

### POST /auth/login
Authenticates with email + password; issues a new session cookie (rotated). Throttled per IP and per account.

### POST /auth/logout
Revokes the current session.

### POST /auth/logout-all
Revokes all sessions of the current user.

### GET /auth/me
Returns the current user and memberships summary.

### GET /auth/sessions
Lists the current user's active sessions.

### DELETE /auth/sessions/{session_id}
Revokes one of the current user's sessions.

### POST /auth/forgot-password
Starts password reset (uniform response).

### POST /auth/reset-password
Completes password reset with a single-use token; revokes all sessions.

### POST /auth/change-password
Changes password for the authenticated user (requires current password); rotates the session.

### ~~POST /auth/refresh~~ — not used
AdVegaX uses server-side sessions in an HttpOnly cookie (Decision D10); there is no client-held refresh token.

Future login methods (Google, Microsoft, enterprise IdPs, MFA, passkeys) are added as new endpoints without changing these.

### 3A. Phase 1A implementation reference

Implemented in `backend/app/domains/identity/router.py`; the generated OpenAPI schema (`/api/v1/openapi.json`, non-deployed environments only) is the authoritative request/response contract.

| Endpoint | Request body | Success | Notes |
|---|---|---|---|
| `GET /auth/csrf` | — | 200 `{csrf_token}` | Sets the HttpOnly CSRF cookie; the client keeps the token in memory and sends it as `X-CSRF-Token` |
| `POST /auth/register` | `{email, password, display_name?}` | 202 `{status: "accepted"}` | Identical response for new and existing emails |
| `POST /auth/verify-email` | `{token}` | 200 `{status: "verified"}` | 400 `INVALID_TOKEN` |
| `POST /auth/resend-verification` | — | 202 | Session required; throttled |
| `POST /auth/login` | `{email, password}` | 200 `{user, csrf_token}` | Sets a new session cookie; 401 `INVALID_CREDENTIALS` |
| `POST /auth/logout`, `/auth/logout-all` | — | 200 `{status, csrf_token}` | Clears the session cookie; returns an anonymous CSRF token |
| `GET /auth/me` | — | 200 `{id, email, display_name, email_verified, memberships[]}` | |
| `GET /auth/sessions` | — | 200 list `{id, created_at, last_used_at, auth_method, user_agent_summary, current}` | |
| `DELETE /auth/sessions/{session_id}` | — | 200 | 404 if not the caller's |
| `POST /auth/forgot-password` | `{email}` | 202 | Uniform response |
| `POST /auth/reset-password` | `{token, new_password}` | 200 `{status, csrf_token}` | Revokes all sessions; marks the email verified |
| `POST /auth/change-password` | `{current_password, new_password}` | 200 `{status, csrf_token}` | Revokes other sessions; issues a new session |

Health probes are served at `GET /api/v1/health/live` and `GET /api/v1/health/ready` (database + Redis).

**Error codes (Phase 1A):** `VALIDATION_ERROR` 422 · `UNAUTHENTICATED` 401 · `INVALID_CREDENTIALS` 401 · `FORBIDDEN` 403 · `EMAIL_NOT_VERIFIED` 403 · `CSRF_FAILED` 403 · `INVITATION_EMAIL_MISMATCH` 403 · `NOT_FOUND` 404 · `METHOD_NOT_ALLOWED` 405 · `CONFLICT` 409 · `SLUG_TAKEN` 409 · `ALREADY_MEMBER` 409 · `LAST_OWNER` 409 · `INVITATION_NOT_PENDING` 409 · `INVALID_TOKEN` 400 · `PAYLOAD_TOO_LARGE` 413 · `UNSUPPORTED_MEDIA_TYPE` 415 · `RATE_LIMITED` 429 · `INTERNAL_ERROR` 500 · `SERVICE_UNAVAILABLE` 503. Validation details list location, message and type only — submitted values are never echoed.

## 4. Organizations (Phase 1A)

### GET /organizations
Organizations where the user has an active membership.

### POST /organizations
Create organization; the creator becomes Owner.

### GET /organizations/{organization_id}
### PATCH /organizations/{organization_id}

### GET /organizations/{organization_id}/members
### PATCH /organizations/{organization_id}/members/{member_id}
Change role/status (cannot remove or demote the last Owner).
### DELETE /organizations/{organization_id}/members/{member_id}

### POST /organizations/{organization_id}/invitations
Invite by email with a role; sends an invitation email.
### GET /organizations/{organization_id}/invitations
### DELETE /organizations/{organization_id}/invitations/{invitation_id}
Revoke.
### POST /invitations/accept
Accept with a single-use token; the authenticated user's verified email must match.

### GET /organizations/{organization_id}/audit-logs
See §18.

All organization endpoints resolve membership and role server-side; a non-member receives 404.

Phase 1A request bodies: organization create `{name, slug?, default_currency, default_timezone}` (currency ISO-4217, IANA time zone; slug derived from the name when omitted) · update `{name?, default_currency?, default_timezone?}` · member update `{role?, status?: active|suspended}` · invitation `{email, role}` · accept `{token}`. Unknown fields are rejected (422). Role rules: only Owners grant or remove the Owner role; nobody assigns a role above their own; the last active Owner cannot be removed, demoted or suspended (409 `LAST_OWNER`). Creating organizations and accepting invitations require a verified email (403 `EMAIL_NOT_VERIFIED`).

## 5. External Connections and Resources (Phase 1B — implemented; real providers from Phase 2A)

Approved model A6/A16: organization-owned connection (authorized by a user) → discovered resources → explicit organization links. Implemented in `backend/app/domains/integrations/router.py`; the generated OpenAPI schema is the authoritative contract. In non-deployed environments only the test provider `fake` is registered; deployed environments register no provider until Phase 2A.

Permissions: `connections.view` (all roles) for reads; `connections.manage` (Owner, Admin, Manager) for changes; `jobs.view` (all roles). Non-members get 404. Refused actions are recorded in the audit log (`authorization.denied`).

| Endpoint | Success | Notes |
|---|---|---|
| `GET /providers` | 200 list `ProviderOut` `{code, display_name, category, auth_scheme, capabilities, test_only}` | Any signed-in user. Platforms available in this environment — the fake test platform locally, **empty in staging/production** until Phase 2A. Public metadata only (1C-03) |
| `GET /organizations/{organization_id}/connections` | 200 list `ConnectionOut` | Status, scopes, account label, last error code, `sign_in_expires_at` (Phase 4: when a sign-in that cannot be renewed ends — Meta, ~60 days; null otherwise and once disconnected; also on the detail route) — never secrets |
| `POST /organizations/{organization_id}/connections/{provider}/start` | 200 `{authorize_url, expires_in_seconds}` | Creates single-use state (Redis, `CONNECT_STATE_TTL`) bound to user + organization + provider + PKCE verifier + validated connect parameters. **Optional body (2A-03):** `{"params": {…}}` (≤ 5 keys, values ≤ 255 chars), validated by the provider — Shopify requires `{"shop_domain": "eve-zone"}` (also accepts `eve-zone.myshopify.com` or a pasted store URL); **WooCommerce (2B-04)** requires `{"store_url": "shop.example.com/store"}` (normalized: HTTPS, public name, optional sub-folder) and first checks that the address answers with a WooCommerce REST API — **422 `STORE_NOT_REACHABLE`** with `details: [{"reason": <code>}]` otherwise (e.g. `woocommerce_api_not_found`, `retryable`, `store_redirected`); its `authorize_url` is the store's own `/wc-auth/v1/authorize` page (scope `read`). Other providers refuse any parameter. Errors: 422 `INVALID_CONNECT_PARAMS`; **409 `ACCOUNT_IN_USE`** when the platform account (e.g. the store) is live in another organization (Q6) |
| `GET /connections/{provider}/callback` | 303 → `APP_BASE_URL/connections?status=…` | Organization comes **only** from the validated state. `status=connected&organization_id=…&connection_id=…`, `status=cancelled&organization_id=…`, or `status=error&code=` `invalid_state` / `session_mismatch` / `not_permitted` / provider error code. `organization_id` is included only after the state is validated and the signed-in user is confirmed as a manager of that organization (cancelled, provider error, connected) — never for `invalid_state`, `session_mismatch` or `not_permitted` (1C-03). **2A-03:** the one-live-connection rule is checked **before** the token exchange (`code=account_in_use`); Shopify adds `invalid_signature`, `account_mismatch`, `missing_scopes`, `invalid_connect_params`. Reconnecting the same platform account from the same organization **reuses** the existing connection (`connection.reconnected` in the audit log). Hidden from OpenAPI |
| `POST /connections/{provider}/credentials` | 200 `{"status": "accepted"}` | **2B-04.** Platforms with key delivery (WooCommerce) post the generated key here, server to server: **no session or CSRF** (exact path exempt), JSON ≤ 4 KB, `THROTTLE_KEY_DELIVERY_PER_IP_PER_MINUTE` (30). Authenticated by the single-use connect state echoed as `user_id` (consumed at once). Only a `read` key is accepted, and it is verified against the store recorded at start before it is stored. Any failure: **422 `INVALID_KEY_DELIVERY`**, nothing echoed. The outcome is kept for `CONNECT_STATE_TTL` for the browser's return. Hidden from OpenAPI |
| `GET /connections/{provider}/callback` (key delivery) | 303 → `APP_BASE_URL/connections?status=…` | **2B-04.** For key-delivery platforms the callback is the browser's return (`success`, `user_id`): it shows the delivered outcome once, only to the same signed-in person — `connected`, `cancelled` (merchant declined; the state is retired), or `error` with `key_not_delivered`, `not_read_only`, `key_rejected`, `auth_header_stripped`, `woocommerce_too_old`, `account_in_use`, `not_permitted`, `session_mismatch`, `invalid_state` |
| `GET /organizations/{organization_id}/stores[/{store_id}]` (2B-06 additions) | `StoreOut` | New optional fields for self-hosted stores: `site_url`, `platform_version`, `health: {code, checked_at}` (code: `woocommerce_too_old` / `timezone_unknown` / `cost_of_goods_off`, or a provider error code when the daily check itself failed; `null` = fine), `counted_statuses` (order statuses the figures count). Empty for Shopify |
| `GET /connections/{provider}/install` | 303 → `APP_BASE_URL/connect/{provider}?account=…` or `APP_BASE_URL/connections?status=error&code=…` | **2A-03.** Platform-initiated install (Shopify install link; later the App Store). Public, signature-verified (HMAC + timestamp ≤ `SHOPIFY_INSTALL_MAX_AGE`), stores nothing: the web app then asks the person to sign in and choose the organization, which starts the normal state-protected flow. Errors: `invalid_signature`, `invalid_connect_params`, `unsupported`, `unknown_provider`. Hidden from OpenAPI |
| `GET /organizations/{organization_id}/connections/{connection_id}` | 200 `ConnectionOut` | |
| `POST /organizations/{organization_id}/connections/{connection_id}/disconnect` | 200 `ConnectionOut` | Revokes at the provider where supported (failure tolerated and recorded), erases ciphertext, ends active links (`connection_revoked`), status `revoked` |
| `POST /organizations/{organization_id}/connections/{connection_id}/rediscover` | 202 `JobOut` | Queues a discovery job |
| `GET /organizations/{organization_id}/connections/{connection_id}/resources` | 200 list `ResourceOut` | Includes capabilities, `linked`, `link_id`, `last_synced_at`; (Phase 3) `unavailable_reason` (plain key such as `account_not_enabled`, `developer_token_not_approved`, `account_details_missing`) and `group_path` (e.g. the manager accounts above an ad account) |
| `POST /organizations/{organization_id}/resources/{resource_id}/link` | 201 `LinkOut` | Explicit; audited; (Phase 3) refused with `RESOURCE_UNAVAILABLE` 409 and `details: [{reason}]` when the resource has an `unavailable_reason` |
| `POST /organizations/{organization_id}/resources/{resource_id}/unlink` | 200 `LinkOut` | History kept (`unlink_reason=user`) |
| `GET /organizations/{organization_id}/resources/{resource_id}/links` | 200 list `LinkOut` | Link history |
| `POST /organizations/{organization_id}/resources/{resource_id}/sync` | 202 `JobOut` | Resource must be actively linked |
| `GET /organizations/{organization_id}/jobs/{job_id}` | 200 `JobOut` | Status, attempts, last error code |

**Error codes (Phase 1B):** (3-08) `AD_ACCOUNT_NOT_SYNCING` 409 · `UNKNOWN_PROVIDER` 404 · (2B-04) `STORE_NOT_REACHABLE` 422 · `INVALID_KEY_DELIVERY` 422 · `CONNECTION_NOT_ACTIVE` 409 · `RESOURCE_NOT_LINKABLE` 409 · (3-04) `RESOURCE_UNAVAILABLE` 409 · `ALREADY_LINKED` 409 · `NOT_LINKED` 409 (plus the Phase 1A codes, e.g. `FORBIDDEN`, `NOT_FOUND`, `SERVICE_UNAVAILABLE` when Redis is unavailable for connect state).

Third-party platform authorization is a separate security domain from AdVegaX login (Decisions D7, D10).

## 6. Stores

### GET /organizations/{organization_id}/stores
List stores.

### GET /organizations/{organization_id}/stores/{store_id}
Get store.

### POST /organizations/{organization_id}/stores/{store_id}/sync
Queue store synchronization.

## 7. Products

### GET /organizations/{organization_id}/products
Filters:
- search
- status
- store
- inventory
- margin

### GET /organizations/{organization_id}/products/{product_id}

### PATCH /organizations/{organization_id}/products/{product_id}
Update internal product metadata such as cost when permitted.

### POST /organizations/{organization_id}/products/{product_id}/sync
Queue provider sync.

## 8. Advertising Accounts

### GET /organizations/{organization_id}/ad-accounts

### GET /organizations/{organization_id}/ad-accounts/{ad_account_id}

### POST /organizations/{organization_id}/ad-accounts/{ad_account_id}/sync
*As built (3-08): `…/resync` — see §19B.*

## 9. Campaigns

### GET /organizations/{organization_id}/campaigns
Filters:
- provider
- account
- status
- date range

### GET /organizations/{organization_id}/campaigns/{campaign_id}

### POST /organizations/{organization_id}/campaigns/validate
Validate proposed campaign configuration without creating it.

### POST /organizations/{organization_id}/campaigns
Create campaign only after:
- authorization,
- validation,
- budget checks,
- idempotency.

Accept `Idempotency-Key`.

### PATCH /organizations/{organization_id}/campaigns/{campaign_id}
Update permitted campaign fields.

### POST /organizations/{organization_id}/campaigns/{campaign_id}/pause

### POST /organizations/{organization_id}/campaigns/{campaign_id}/resume

### POST /organizations/{organization_id}/campaigns/{campaign_id}/sync

## 10. Creatives

> **Superseded by §19I (as built, Phase 9).** The outline below is kept for history.

### GET /organizations/{organization_id}/creatives

### POST /organizations/{organization_id}/creatives

### PATCH /organizations/{organization_id}/creatives/{creative_id}

### POST /organizations/{organization_id}/creatives/{creative_id}/approve

### POST /organizations/{organization_id}/creatives/{creative_id}/reject

Approval must be recorded in audit history.

## 11. AI Strategy

> **Superseded by §19H (as built, Phase 8, task 8-05).** The outline below is kept for history.

### POST /organizations/{organization_id}/ai/campaign-strategy

Input:
- product_id
- platform
- objective
- market
- budget
- constraints

Output must be structured and schema validated.

Example conceptual output:
```json
{
  "strategy": {
    "objective": "conversion",
    "market": "AU",
    "channel": "google_ads",
    "campaign_type": "...",
    "positioning": ["..."],
    "audience": ["..."],
    "creative_angles": ["..."],
    "budget_allocation": [],
    "risks": [],
    "assumptions": []
  }
}
```

AI response must never directly create a campaign.

## 12. AI Creative Generation

> **Superseded by §19I (as built, Phase 9).** The outline below is kept for history.

### POST /organizations/{organization_id}/ai/creative-ideas

Input:
- product
- strategy
- platform
- market
- tone
- constraints

Output:
- creative concepts,
- copy variants,
- CTA,
- rationale,
- compliance notes.

All output is draft content until approved.

## 13. Recommendations

### GET /organizations/{organization_id}/recommendations

### GET /organizations/{organization_id}/recommendations/{recommendation_id}

### POST /organizations/{organization_id}/recommendations/{recommendation_id}/approve

### POST /organizations/{organization_id}/recommendations/{recommendation_id}/reject

Approval should create an executable action request, not directly bypass the Action Engine.

## 14. Actions

> **Superseded by §19J (Phase 10A, as built).** Kept for history (A1).

### POST /organizations/{organization_id}/actions/validate

Validates proposed action.

### POST /organizations/{organization_id}/actions/{action_id}/execute

Executes an already approved action.

### GET /organizations/{organization_id}/actions/{action_id}

Only the Action Engine can perform external mutations.

## 15. Analytics

### GET /organizations/{organization_id}/analytics/overview
Returns:
- impressions,
- clicks,
- CTR,
- CPC,
- spend,
- conversions,
- CPA,
- revenue,
- ROAS,
- profit.

### GET /organizations/{organization_id}/analytics/campaigns

### GET /organizations/{organization_id}/analytics/products

### GET /organizations/{organization_id}/analytics/funnel

### GET /organizations/{organization_id}/analytics/financial

All financial figures come from deterministic backend calculations.

## 16. Funnel

### GET /organizations/{organization_id}/funnel
Parameters:
- start_date
- end_date
- product_id
- campaign_id
- platform

Response includes stage counts and conversion rates.

## 17. Automation

### GET /organizations/{organization_id}/automation/policy

### PUT /organizations/{organization_id}/automation/policy

### POST /organizations/{organization_id}/automation/enable

### POST /organizations/{organization_id}/automation/disable

Enabling autopilot requires appropriate role and explicit confirmation.

## 18. Audit

### GET /organizations/{organization_id}/audit-logs

Filters (Phase 1A query parameters): `actor_user_id`, `action`, `resource_type`, `created_from`, `created_to` (ISO 8601), `result` (success | denied | failed); pagination `page` (≥ 1) and `page_size` (1–100, default 50). Newest first. Owners and Admins only (A15).

Never expose secret fields.

## 19. Billing

### GET /organizations/{organization_id}/billing

### POST /organizations/{organization_id}/billing/checkout

### POST /organizations/{organization_id}/billing/change-plan

### POST /organizations/{organization_id}/billing/cancel

### POST /billing/webhooks/provider

Billing webhooks must be signature-verified and idempotent.

## 19A. Stores, products and daily figures — as built (2A-09)

All under `/organizations/{organization_id}`; membership resolved server-side, RLS + explicit organization filters; another organization's store/product → 404. Money is an exact decimal **string** in the store currency (`currency_minor_units` says how to round for display); anything missing has an `availability` (`available` / `unavailable` / `unsupported` / `not_synchronized`) and a `reason`, never a 0.

| Method & path | Who | Notes |
|---|---|---|
| `GET /stores` | all members | Stores with `status`, `linked`, `connection_status`, `history_from`, `first_import_completed_at`, `sync {running, mode, progress, last_reconciled_at, last_deep_reconciled_at, last_error_code, last_error_at}` |
| `GET /stores/{store_id}` | all members | One store (same shape) |
| `POST /stores/{store_id}/resync` | owner, admin, manager | "Sync now": a deep check (whole catalogue + recent orders). 202 `{store_id, job_id, mode}`; 409 `SYNC_IN_PROGRESS` (import or sync running), 409 `STORE_NOT_SYNCING` (unlinked / connection not active); 429 above `THROTTLE_STORE_RESYNC_PER_HOUR` per store |
| `GET /stores/{store_id}/products?cursor&page_size(1–100, 50)&q&status` | all members | Ordered by title; cursor pagination (`next_cursor`); `q` matches title or SKU (literal text, no wildcards); `status` one of `active/draft/archived/unlisted/deleted` (deleted hidden by default). Each variant has `inventory {availability, tracked, available, synced_at}` and `cost {availability, unit_cost, source, effective_from, reason}` |
| `GET /stores/{store_id}/products/{product_id}` | all members | One product with variants |
| `GET /stores/{store_id}/metrics/daily?from&to` | all members | Default the last 30 store-local days; at most `METRICS_MAX_DAYS`. `definition_version` (`finance-v1`), `synced_from` (first fully covered day), per-day components and `cogs` / `gross_profit` / `cost_coverage` figures; days before `synced_from`, before the first import or in the future are `not_synchronized` (values null). `totals` adds `gross_margin`, `shipping_cost`, `payment_fees`, `new_vs_returning`; totals are `not_synchronized` if any day in the period is. **2B-07:** days and totals also carry a `reason`; a day with orders in another currency is `unavailable` with reason `other_currency_orders` (all values null, never 0), and so are the totals of a period containing one (`not_synchronized` takes precedence). Orders that do not count (`excluded_reason`) are never in the figures |

## 19B. Ad accounts, campaigns and figures — as built (3-08)

All under `/organizations/{organization_id}`; same rules as §19A (server-side membership, RLS plus explicit organization filters, another organization's ad account or campaign → 404, exact decimal strings, `availability` + `reason` on anything missing). Permissions: `ads.view` (all members), `ads.manage` (owner, admin, manager). Every answer carries `source: "platform_reported"`: the figures are the platform's own, in the **ad account's** currency (`currency_minor_units` for display) and time zone. No ROAS against store sales and no attribution (Phase 6).

| Method & path | Who | Notes |
|---|---|---|
| `GET /ad-accounts` | all members | `name`, `external_account_id`, `group_path` (managers above it, display only), `currency`, `timezone`, `status` (`importing/active/error/disconnected`), `platform_status`, `linked`, `connection_status`, `connection_expires_at` (Phase 4: when the sign-in behind it ends — Meta, ~60 days; null for Google Ads), `history_from`, `first_import_completed_at`, `sync {running, mode, progress, waiting_for_allowance, last_quick_at, last_nightly_at, last_weekly_at, last_error_code, last_error_at}`, `health {code, checked_at}` |
| `GET /ad-accounts/{ad_account_id}` | all members | One account (same shape). Unlinked accounts stay readable |
| `POST /ad-accounts/{ad_account_id}/resync` | owner, admin, manager | "Sync now": structure + the last 30 days (the first import again if it did not finish). 202 `{ad_account_id, job_id, mode}`; 409 `SYNC_IN_PROGRESS`; 409 `AD_ACCOUNT_NOT_SYNCING` (unlinked / connection not active); 429 above `THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR` per account |
| `GET /ad-accounts/{ad_account_id}/metrics/daily?from&to` | all members | Account-level days, default the last 30 account-local days, at most `METRICS_MAX_DAYS`; 422 `VALIDATION_ERROR` for an invalid range. `synced_from`, `settled_until` (days after it are `settled: false`: the platform may still change them; `ADS_UNSETTLED_DAYS`, 3). Per day and in `totals`: `impressions`, `clicks`, `cost`, `conversions`, `conversion_value` and the derived `click_through_rate` (clicks ÷ impressions, a fraction), `cost_per_click`, `cost_per_conversion`, `conversion_value_per_cost` (six decimals, half-even), each `unavailable` with `no_impressions` / `no_clicks` / `no_conversions` / `no_cost` when its divisor is 0. A day not read (before `synced_from`, before the first import, in the future) is `not_synchronized` with null values, and so are the totals of a period containing one. A day read with no activity has real zeros |
| `GET /ad-accounts/{ad_account_id}/campaigns?from&to` | all members | Every campaign, removed ones included, ordered by name: `status`, `platform_type`, `bidding_strategy_type`, dates, `budget {name, period, amount, currency, shared}` and `figures` for the period from **campaign-level** rows (zeros when the period was read and the campaign had no activity; `not_synchronized` when part of the period was not read) |
| `GET /campaigns/{campaign_id}?from&to` | all members | One campaign (with `provider`, `synced_from`) with its figures and `ad_groups[]` (budget, figures, `ads[]` with their figures), each from its own level; Performance Max campaigns have figures and no ad groups |

Levels are never added into each other: account totals come from account rows, a campaign's from campaign rows. Figures of entities AdVegaX could not store (e.g. an unknown status) count in the account totals but are not listed.

## 19C. Analytics properties and figures — as built (5-07)

All under `/organizations/{organization_id}`; same rules as §19A and §19B (server-side membership, RLS plus explicit organization filters, another organization's property → 404, exact decimal strings, `availability` + `reason` on anything missing). Permissions: `analytics.view` (all members), `analytics.manage` (owner, admin, manager). Every answer carries `source: "platform_reported"` ("Reported by Google Analytics"): the figures are the platform's own, in the **property's** currency (`currency_minor_units` for display) and time zone. They are never added to store or ad figures (Phase 6). These routes are separate from the planned cross-source `/analytics/*` overview in §15.

| Method & path | Who | Notes |
|---|---|---|
| `GET /analytics-properties` | all members | `external_property_id`, `name`, `account_name` (the Analytics account, display only), `currency`, `timezone`, `status` (`importing/active/error/disconnected`), `platform_status` (`active/deleted`), `linked`, `connection_status`, `history_from`, `first_import_completed_at`, `sync {running, mode, progress, waiting_for_allowance, last_quick_at, last_nightly_at, last_weekly_at, last_error_code, last_error_at}` (a quota pause is `waiting_for_allowance`, not an error), `health {code, checked_at}` (`no_property_access`, `property_deleted`, `property_details_changed`, `rate_limited`) |
| `GET /analytics-properties/{property_id}` | all members | One property (same shape). Unlinked properties stay readable |
| `POST /analytics-properties/{property_id}/resync` | owner, admin, manager | "Sync now": the last 14 days (the first import again if it did not finish). 202 `{property_id, job_id, mode}`; 409 `SYNC_IN_PROGRESS`; 409 `ANALYTICS_PROPERTY_NOT_SYNCING` (unlinked / connection not active); 429 above `THROTTLE_ANALYTICS_PROPERTY_RESYNC_PER_HOUR` per property |
| `GET /analytics-properties/{property_id}/metrics/daily?from&to&breakdown&limit` | all members | Default the last 30 property-local days, at most `METRICS_MAX_DAYS`; `breakdown` `total` (default), `channel` or `source`; `limit` 1–500 (default 100) items for a breakdown; 422 `VALIDATION_ERROR` otherwise. `synced_from`, `processing_from` (days from it on are `processing: true` — still being processed by Google; `ANALYTICS_PROCESSING_DAYS`, 3). **Total:** `days[]` and `totals`. **Breakdown:** `items[]` (`key`, `channel_group` or `source` / `medium` / `campaign`, `figures` for the period from that value's own rows; most sessions first), `item_count`, and the property's `totals` (never added up from the items); no items when part of the period was not read. Figures: `sessions`, `engaged_sessions`, `new_users`, `key_events`, `purchases`, `purchase_revenue` (purchases minus refunds; can be negative), `total_users` (a figure: the day's count for one day; **`unavailable` with `users_per_day_only` for a period of several days** — users are never added across days or views), the derived `engagement_rate`, `key_events_per_session`, `purchase_conversion_rate`, `revenue_per_session` (six decimals, half-even; `unavailable` with `no_sessions` when there were none), and `quality {other_row, thresholded, sampled, truncated}` (for a period: any day). A day not read is `not_synchronized` with null values, and so are the totals of a period containing one. A day read with no activity has real zeros |

## 19D. Store assignment — as built (6-02)

| Method & path | Who | Notes |
|---|---|---|
| `PUT /ad-accounts/{ad_account_id}/store` | owner, admin | Body `{store_id}` (a store of the organization, or `null` = the whole organization). 200 with the ad account (now carrying `store_id`); 422 `VALIDATION_ERROR` `{field: store_id, issue: unknown_store}` for a store that is not the organization's; audited as `ad_account.store_assigned` (only when it changes) |
| `PUT /analytics-properties/{property_id}/store` | owner, admin | The same for an analytics property (`analytics_property.store_assigned`) |

`GET /ad-accounts…` and `GET /analytics-properties…` now include `store_id`. The reporting currency and time zone are the organization's `default_currency` and `default_timezone` (`PATCH /organizations/{organization_id}`, owner and admin).

## 19E. Unified analytics — as built (6-05)

The planned `/analytics/*` routes of §15, made concrete. All under `/organizations/{organization_id}`; `analytics.view` (every member); another organization's data or store → 404. Query: `from`, `to` (default the last 30 days of the **reporting time zone**, at most `METRICS_MAX_DAYS`; 422 otherwise), optional `store_id` (Q-6-1: with one store everything counts for it; with several, only what is assigned to it).

Every answer carries `definitions[] {key, label, unit, formula, note, sources}` for the figures it contains (the overview's registry metrics; the channels, campaigns and products tables' own column definitions, added in 6-08 — `registry.TABLES`), `definition_version` (`analytics-v1`), `reporting_currency` (+ `currency_minor_units`) and `reporting_timezone` (the organization's own settings), `from_day`, `to_day`, `store_id`, `sources[] {kind, id, provider, name, currency, timezone, synced_from, updated_at}`, `conversions[] {currency, rate_sources, first_rate_date, last_rate_date, days_without_rate}` and `notes[]` (`time_zones_differ`). Every figure is `{value, availability, reason}` (exact decimal strings; ratios six decimals); never 0 for missing data.

| Method & path | Notes |
|---|---|
| `GET /analytics/overview` | `totals` and `days[] {day, figures}` with every registry figure: `net_sales`, `orders`, `product_cost`, `gross_profit`, `gross_margin`, `ad_spend`, `profit_after_ad_spend`, `blended_roas`, `cost_per_order`, `ad_spend_share`, `sessions`, `analytics_purchases`, `analytics_revenue`, `store_conversion_rate`, and — not provided in v1 — `shipping_cost`, `payment_fees` (`unsupported` / `not_provided_by_platform`), `contribution_profit` (`unsupported` / `costs_not_entered`), `customer_acquisition_cost` (`unavailable` / `customer_key_not_collected`). Reasons include `not_synchronized`, `missing_product_costs`, `other_currency_orders`, `no_exchange_rate`, `no_store`, `no_ad_account`, `no_analytics_property`, `not_every_store_measured` and the zero divisors `no_net_sales`, `no_ad_spend`, `no_orders`, `no_sessions`. |
| `GET /analytics/channels` | `ad_spend` (all platforms — the only figure added across them); `platforms[] {provider, source: platform_reported, ad_accounts, figures {spend, clicks, impressions, conversions, conversion_value, platform_roas, cost_per_click, cost_per_conversion}}` (each platform's own, never added across platforms); `analytics_channels[] {channel, figures {sessions, engaged_sessions, engagement_rate, key_events, purchases, purchase_revenue}}` most sessions first, or `analytics_channels_missing` saying why there are none |

## 19F. Campaigns and products — as built (6-06)

Same base, permission, query and context fields as §19E.

| Method & path | Notes |
|---|---|
| `GET /analytics/campaigns` | `items[] {id, ad_account_id, provider, source: platform_reported, name, status, budget_period, figures {spend, clicks, impressions, conversions, conversion_value, platform_roas, cost_per_click, cost_per_conversion, budget_use}, analytics, analytics_missing}` by name. Spend converted to the reporting currency with each day's rate; a campaign read with no activity has a real 0 spend. `budget_use` = spend / (today's daily budget x days) — `unsupported` / `not_a_daily_budget` for a lifetime budget, `unavailable` / `shared_budget` or `no_budget`. `analytics {sessions, purchases, purchase_revenue}`: Google Analytics' figures for the campaign of exactly the same name (Google: google / cpc; Meta: facebook or instagram / paid or cpc) — `unavailable` / `no_match` when none; `analytics` null with `analytics_missing` (`no_analytics_property`, `not_synchronized`) |
| `GET /analytics/products` | `items[] {product_id, store_id, title, figures {units, net_sales, product_cost, gross_profit, gross_margin}}` most net sales first (finance-v1 per product; `product_cost` `unavailable` / `missing_product_costs` when a sold line has no cost); no ad spend per product. `items_missing` says why there are none (`no_store`, `not_synchronized`); `other_currency_lines` counts sold lines in another currency, left out |

## 19G. Funnel — as built (7-06)

`GET /organizations/{organization_id}/analytics/funnel`, `…/funnel/campaigns`, `…/funnel/landing-pages`: same base, permission (`analytics.view`), query (`from`, `to`, `store_id`) and context fields as §19E, with `definition_version` **`funnel-v1`** and `definitions[]` describing the stages (`unit: count`, `sources`: `ads` | `google_analytics` | `stores`). Stages count **events, not people**; every stage is `{value, availability, reason}`; a step is `{from_stage, to_stage, kind, rate}` with `kind` `same_source` (a rate), `different_sources` (`rate: null`) or `store_conversion` (orders ÷ sessions; `not_every_store_measured` otherwise). Reasons include `not_synchronized` (a day not read, or not yet re-read with the funnel figures), `no_ad_account`, `no_analytics_property`, `no_store`, `not_provided_by_platform`, `no_events_reported` (visits but no ecommerce events), `no_match`, and the zero divisors `no_impressions`, `no_clicks`, `no_sessions`, `no_product_views`, `no_adds_to_cart`, `no_checkouts`.

| Method & path | Notes |
|---|---|
| `GET /analytics/funnel` | `stages` (impressions, clicks, landing_page_views, product_views, adds_to_cart, checkouts, purchases = store orders, analytics_purchases), `steps`; `platforms[] {provider, source: platform_reported, ad_accounts, stages, steps}` (Meta: every stage; Google Ads: impressions → clicks → purchases, the rest `unsupported`), `platform_definitions`; `channels[] {channel, stages, steps}` most visits first, or `channels_missing`; `findings[] {view, subject, from_stage, to_stage, rate, previous_rate, baseline_rate, events_before, change}` largest fall first (Q-7-7), and `rules {drop_share, min_events, baseline_days, previous_from, previous_to}` |
| `GET /analytics/funnel/campaigns` | `items[] {id, ad_account_id, provider, source, name, status, stages, steps, analytics, analytics_steps, shared_match}` — the platform's own funnel and Google Analytics' funnel for the campaign of exactly the same name (Q-6-9 rules; `no_match` otherwise); `other_traffic`, `other_traffic_steps` and `website` (the source view: matched campaigns, each match counted once, plus other traffic), or `analytics_missing` |
| `GET /analytics/funnel/landing-pages` | `items[] {landing_page, stages, steps}` — Google Analytics' funnel per landing page (paths only), most visits first, at most 100; `item_count`; `items_missing` (`no_analytics_property`, `not_synchronized`) |

## 19H. Campaign strategies — as built (8-05)

Base `/organizations/{organization_id}/ai`. Permissions: `strategies.view` (every role), `strategies.manage` (owner, admin, manager, analyst — generate, edit, ready, archive), `ai_usage.view` (owner, admin). Every change is audited (`campaign_strategy.generated | edited | ready | archived`; the audit keeps status, objective, platforms and budget — never strategy text). Nothing is created at Google or Meta.

| Method & path | Notes |
|---|---|
| `POST /campaign-strategies` (201) | Body `{product_id, platforms: ["google_ads" \| "meta_ads"] (1–2, distinct), objective: "sales" \| "leads" \| "awareness" \| null, budget: {amount > 0 (at most the currency's minor units), period: "daily" \| "monthly"}}` in the reporting currency. Checks before the model: `PRODUCT_NOT_PLANNABLE` (422) with `details[] {reason}` — `product_not_active`, `out_of_stock`, `no_ad_platform`, `platform_not_connected:<p>`, `budget_too_small`, `budget_minimum_not_checkable`. Then one model call (one retry): `AI_LIMIT_REACHED` (429, daily runs per organization), `AI_UNAVAILABLE` (503: switched off, no key, provider down, time limit), `AI_ANSWER_REJECTED` (422, `details[] {reason}`: the validation reasons of the last answer). On success: the strategy, kept as `draft` |
| `GET /campaign-strategies` | Paged (`page`, `page_size` ≤ 100); `status` (default: all but archived), `product_id`; items `{id, product_id, product_title, status, objective, platforms, budget, created_at, updated_at}`, most recently changed first |
| `GET /campaign-strategies/{strategy_id}` | `{id, product_id, product_title, status, strategy, budget {amount, period, currency}, budget_amounts {<platform>: {amount, daily}}, evidence {<key>: {label, unit, value, availability, reason, currency} \| null}, validated: true, ai_run {id, provider, model, prompt_name, prompt_version, created_at}, created_by, edited_by, edited_at, created_at, updated_at}`. Evidence is resolved from the run's snapshot (the figures as the planner saw them); `null` = a key not in it |
| `PATCH /campaign-strategies/{strategy_id}` | Body `{strategy?: <the whole strategy>, budget?: {amount, period}}`; re-validated with the same chain as the model's answers (8-04), against today's figures; failures `VALIDATION_ERROR` with `details[] {field: "strategy" \| "budget.amount", issue}`; amounts recomputed; the strategy becomes `draft` again. `STRATEGY_ARCHIVED` (409) for an archived strategy |
| `POST /campaign-strategies/{strategy_id}/ready` | `draft → ready` (unchanged when already ready); `STRATEGY_ARCHIVED` (409) |
| `POST /campaign-strategies/{strategy_id}/archive` | `draft \| ready → archived` (kept, never deleted; unchanged when already archived) |
| `GET /usage` | `{daily_limit, runs_today, remaining_today, ai_enabled, today, last_30_days}`; each period `{runs, succeeded, rejected, failed (incl. timed out), input_tokens, output_tokens, estimated_cost_usd}` — `null` unless every run in the period has a price (prices are settings) |

The strategy object (`strategy`): `{objective, summary, positioning, platforms[] {platform, campaign_type, budget_share_percent, audience, reasoning, evidence[]}, angles[] {angle, evidence[]}, targets[] {metric: roas \| cost_per_order \| cost_per_click \| cost_per_conversion, low, high, evidence[]}, risks[] {code, text}, assumptions[]}` — no money amounts (Q-8-5).

## 19I. Creatives — as built (Phase 9)

Base `/organizations/{organization_id}`. Permissions: `creatives.view` (every role), `creatives.manage` (all but viewers: draft, edit, upload), `creatives.approve` (owner, admin, manager: approve, reject, archive); the organization's rules are changed by owners and admins (`organization.update`). Every change is audited (`creative_set.generated`, `creative.edited | approved | rejected | archived`, `creative_asset.uploaded | archived`, `creative_rules.updated`) — versions, statuses and reasons, never the ad text. Nothing is sent to Google or Meta.

| Method & path | Notes |
|---|---|
| `POST /ai/creative-sets` (201) | Body `{strategy_id}` — a **ready** strategy (`STRATEGY_NOT_READY`, 409, otherwise). One AI run drafts every platform of the strategy; every concept is kept as version 1, `draft`, with its `checks`. Errors: `AI_LIMIT_REACHED`, `AI_UNAVAILABLE`, `AI_ANSWER_REJECTED` (`details[] {reason}` like `google_ads[0].too_long:headlines[2]=30`) |
| `GET /creative-sets[?strategy_id]`, `GET /creative-sets/{set_id}` | Summaries `{id, strategy_id, product_title, created_at, concepts, approved}`; one set with the newest version of each concept |
| `GET /creatives[?status&platform&strategy_id]` | With `status=approved`: what the campaign builder may use |
| `GET /creatives/{creative_id}` | `{id, set_id, strategy_id, product_id, product_title, concept_id, version, latest, platform, format, angle, status, content, rationale, compliance_notes, checks[] {code, field, detail, severity: block \| flag}, approvable, asset, decided_by, decided_at, decision_reason, created_by, created_at, versions[]}` |
| `PATCH /creatives/{creative_id}` | Body `{content?, asset_id?, remove_asset?}`; only the newest, not archived version (`CREATIVE_NOT_EDITABLE`, 409); makes a **new draft version** with fresh checks; `asset_id` only for Meta (`meta_only`) and an active image of the organization |
| `POST /creatives/{creative_id}/approve` | Body `{confirm_flags}`; checks run again with today's rules and catalogue prices: `CREATIVE_CHECKS_FAILED` (422, `details[] {reason, field, detail, severity}`) for any blocking result, or flagged wording not confirmed; the concept's previously approved version is archived |
| `POST /creatives/{creative_id}/reject` | Body `{reason}` (3–500 characters); drafts only |
| `POST /creatives/{creative_id}/archive` | Kept, never deleted |
| `POST /creative-assets` (201) | `multipart/form-data` with `file` (the only multipart route; size limit `ASSET_MAX_BYTES` + form overhead, else 413). Decoded (JPEG, PNG, WebP), pixel limit, smallest side, re-encoded without metadata; `ASSET_INVALID` (422, `details[] {reason}`: `not_an_image`, `unsupported_type`, `too_small`, `too_large`, `too_many_pixels`, `empty`) |
| `GET /creative-assets[?archived]`, `GET /creative-assets/{asset_id}/content`, `POST /creative-assets/{asset_id}/archive` | The image itself only through the API, for members (`Cache-Control: private`) |
| `GET /creative-rules`, `PUT /creative-rules` | `{prohibited_terms[], allowed_caps[], base_prohibited_terms[], updated_at}` |

## 19J. Changes to ad accounts (Action Engine) — as built (Phase 10A)

Base `/organizations/{organization_id}`. Supersedes §14. Permissions: `actions.view` (every role), `actions.request` (owner, admin, manager: validate, request, cancel their own, undo), `actions.approve` (owner, admin: approve, reject, cancel any), `actions.settings` (owner, admin: settings and "Allow changes"). The installation switch `ACTIONS_ENABLED` (off by default) and the organization's `paused` stop requests, approvals and sending (`ACTIONS_DISABLED`, 409). Every step is in `action_events` and the audit log (`action.requested | approved | queued | submitting | succeeded | failed | unknown | stale | rejected | cancelled | verified`, `action_settings.updated`, `connection.write_access_granted | removed`) — never a token.

| Method & path | Notes |
|---|---|
| `POST /actions/validate` | Body `{action_type: campaign.pause \| campaign.resume \| campaign.set_daily_budget, campaign_id, params}` (`params.daily_budget` as a string in the ad account's currency, budgets only). Runs every check and the platform's dry run; keeps nothing. Answer `{passed, checks[] {check: shape \| resource \| budget \| limits \| state, result: passed \| failed \| skipped, reason}, dry_run {result, reason}, current {status, budget_level, budget_period, daily_budget, budget_shared}, budget_limits {lowest, highest, platform_minimum, organization_maximum, increase_percent, decrease_percent} \| null, currency, currency_minor_units}` |
| `POST /actions` (201) | The same checks and dry run; kept as `pending` only if all pass (`ACTION_INVALID`, 422, `details[] {check, reason}`, the dry run as `check: dry_run`). An identical open request: `ACTION_DUPLICATE` (409); another open change of the campaign: reason `campaign_has_open_change`; changes not allowed for the connection: `ACTION_NOT_ALLOWED` (409, `details[] {reason: changes_not_allowed \| permission_missing \| platform_cannot_change}`) |
| `GET /actions[?status=open\|<status>&campaign_id&page&page_size]`, `GET /actions/{action_id}` | `{id, action_type, provider, campaign {id, name, external_id, ad_account_id, ad_account_name}, currency, currency_minor_units, params, previous, observed, status, checks, dry_run, verification: verified \| mismatch \| not_checked \| null, error_code, platform_request, platform_answer, source, undo_of, requested_by, decided_by, decided_at, decision_reason, submitted_at, finished_at, created_at, updated_at, can_undo, events[] {from_status, status, actor_type, actor_user_id, detail, created_at}}` (events on the single read) |
| `POST /actions/{action_id}/approve` | Pending only (409 otherwise). Checks run again with today's limits; queued for the worker. `SECOND_PERSON_REQUIRED` (409) when the organization requires it and the approver asked; `ACTION_STALE` (409) after `ACTIONS_PENDING_TTL` |
| `POST /actions/{action_id}/reject` | Body `{reason}` (1–500); pending only |
| `POST /actions/{action_id}/cancel` | Pending, approved or queued; the requester or an owner/admin |
| `POST /actions/{action_id}/undo` (201) | A succeeded, not mismatched change, once: the opposite change as a new `pending` request (`undo_of`); no step or frequency limit, every other check |
| `GET /action-settings`, `PUT /action-settings` | `{engine_enabled, paused, require_second_person, max_daily_budget (reporting currency; null = not chosen, budget changes refused), currency, currency_minor_units, increase_percent, decrease_percent, budget_change_interval_minutes, daily_limit_per_account, updated_at}`; lifting `paused` sends what was queued |
| `GET /connections/{connection_id}/write-access`, `PUT …` | Body `{allowed}`. `{connection_id, provider, supported, allowed, allowed_at, allowed_by, missing_permissions[], can_request_permission}`. Meta needs `ads_management`: sign in again with `POST /connections/meta_ads/start {"params": {"access": "changes"}}` (when `META_WRITE_LOGIN_CONFIG_ID` is set) |

**Statuses:** `pending → approved → queued → submitting → succeeded | failed | unknown`; `unknown → succeeded | failed` (looked up, never sent again); `pending | queued → stale`; `pending → rejected`; `pending | approved | queued → cancelled`. **Reasons** (lower-case codes shown in plain words by the web app): shape `daily_budget_required | daily_budget_invalid | daily_budget_precision | unexpected_values`; resource `platform_cannot_change | account_not_linked | connection_inactive | account_not_active | campaign_not_changeable | campaign_has_open_change | campaign_unavailable | connection_needs_attention`; budget `budget_on_ad_sets | budget_not_daily | budget_shared | no_change`; limits `increase_too_large | decrease_too_large | below_platform_minimum | minimum_not_checkable | above_maximum | maximum_not_checkable | maximum_not_set | budget_changed_recently | daily_limit_reached`; state `already_paused | already_active | campaign_not_changeable`; worker `campaign_changed | outcome_unknown | not_applied | changed_elsewhere | needs_checking | request_expired` and the platform's refusal codes.

## 19K. Campaign builder — as built (Phase 10B; A29)

Base `/organizations/{organization_id}`. Permissions: reading needs `actions.view` (every role); creating, editing, checking and requesting needs `actions.request` (owner, admin, manager); the launch, Go live and clean-up are Action Engine changes (§19J), approved by an owner or admin with `actions.approve`. The installation switch `ACTIONS_ENABLED` and the organization's `paused` stop checking and requesting (`ACTIONS_DISABLED`, 409). Everything is created **paused**; nothing is spent until a second approved change ("Go live").

| Method & path | Notes |
|---|---|
| `POST /campaign-drafts` (201) | Body `{strategy_id, platform: google_ads \| meta_ads, ad_account_id}`. The strategy must be ready and include the platform, with an approved creative for it (`CREATIVE_NOT_APPROVED`, 409). Filled in from the strategy: the daily budget (the strategy's amount, converted to the account currency), the country of the currency, the store's landing page, a name `"{product} - Search\|Sales - AVX-XXXXXX"` |
| `GET /campaign-drafts[?strategy_id]`, `GET /campaign-drafts/{draft_id}` | `{id, strategy_id, product_title, platform, ad_account_id, ad_account_name, creative {…summary}, name, reference, daily_budget, monthly_estimate, currency, currency_minor_units, locations[], age_min, age_max, keywords[] {text, match}, landing_url, meta_page_id, meta_pixel_id, bidding, declarations_confirmed, version, status, created_ids, campaign_id, error_code, editable, open_action_id, created_at, updated_at}` |
| `PATCH /campaign-drafts/{draft_id}` | Draft status only (`DRAFT_NOT_EDITABLE`, 409). Any of name, daily_budget, locations, age_min/age_max (Meta), keywords (Google; `match` phrase by default, exact or broad), landing_url, meta_page_id, meta_pixel_id / `remove_pixel`, `confirm_declarations`. A change other than the declarations resets them and raises `version` |
| `POST /campaign-drafts/{draft_id}/archive` | A draft not launched |
| `POST /campaign-drafts/{draft_id}/validate` | Every check and the platform's test (Google: `validateOnly` of the whole request; Meta: the campaign object only); keeps nothing. `{draft, passed, checks[] {check: creative \| keywords \| targeting \| landing_page \| budget \| meta \| declaration \| limits, result, reason}, dry_run, budget_limits}` |
| `POST /campaign-drafts/{draft_id}/launch` (201) | The same checks; a `campaign.create` change, `pending` (`DRAFT_INVALID`, 422, `details[] {check, reason}`). Approval checks again (`draft_changed` when edited since) |
| `POST /campaign-drafts/{draft_id}/go-live` (201) | Status `created` only: a `campaign.go_live` change, `pending` |
| `POST /campaign-drafts/{draft_id}/clean-up` (201) | Status `failed` with something created: a `campaign.remove_draft_objects` change, `pending` |
| `GET /ad-accounts/{ad_account_id}/meta-pages`, `…/meta-pixels` | The Facebook Pages (`pages_show_list`) and pixels the signed-in Meta user can use: `[{id, name}]` |

**Statuses:** `draft → launching → created → live`; `launching → failed` (a stop part-way: what was made is kept paused and listed in `created_ids`); `draft → archived`. **Never twice:** every name carries the reference; before sending, and after a lost answer, the platform is searched for it. **Google:** one `googleAds:mutate` (budget, campaign PAUSED, locations, ad group, keywords, responsive search ad), Maximize conversions when the account recorded conversions in the last 30 days, else Maximize clicks. **Meta:** image, campaign (OUTCOME_SALES), ad set (purchases with a pixel, else link clicks), creative, ad — each PAUSED. **Reasons:** creative `account_not_linked | connection_inactive | account_not_active | platform_cannot_change | strategy_not_ready | platform_not_in_strategy | creative_not_for_this_campaign | creative_not_approved | image_required | name_invalid`; keywords `keywords_required | too_many_keywords | match_type_invalid:N | keyword_empty:N | keyword_too_long:N | keyword_characters:N | keyword_duplicate:N | keyword_prohibited:N` (N the line, from 0); targeting `locations_required | location_not_supported | ages_invalid`; landing page `landing_url_required | landing_url_not_https | landing_url_invalid | landing_url_not_store` (the store's domain, its subdomains, or a domain added in the change settings `landing_domains`); budget as §19J plus `daily_budget_invalid`; meta `page_required | pixel_invalid`; `declaration_required`; limits `daily_limit_reached`; worker `draft_changed | build_incomplete | outcome_unknown | not_applied | nothing_to_remove`.

`PUT /action-settings` (§19J) also takes `landing_domains[]` (up to 10 host names; `landing_domain_invalid`).

## 20. Webhooks

Provider webhooks must:
- verify authenticity,
- resolve tenant safely,
- record event ID,
- enforce idempotency,
- queue processing,
- acknowledge quickly,
- retry failed internal processing.

### POST /webhooks/{provider} — as built (2A-05)

Machine-to-machine (not in the OpenAPI schema used by the web app). One URL per platform for every topic, including Shopify's three privacy topics (`/api/v1/webhooks/shopify`).

- **Authentication:** the platform's signature over the **raw** body (Shopify: base64 HMAC-SHA256, `X-Shopify-Hmac-Sha256`). No session, no Origin/CSRF check — this exact path shape is the only exemption in the request guard; body-size (1 MB) and `application/json` limits still apply. Per-IP rate limit `THROTTLE_WEBHOOK_PER_IP_PER_MINUTE`.
- **Responses:** `200 {"data": {"status": "accepted" | "duplicate" | "ignored"}}`; `401 INVALID_SIGNATURE` (bad/missing signature, or triggered outside `WEBHOOK_MAX_AGE` / `WEBHOOK_CLOCK_SKEW` — possible replay; nothing stored); `400 INVALID_WEBHOOK` (signed but malformed); `404` for a platform without webhooks; `413`, `415`, `429`.
- **Stored:** metadata only in `webhook_events` (webhook id, topic, account, object id, timestamps, organization, status); the body is discarded. Redeliveries (same webhook id) are `duplicate`. Unknown stores and unsubscribed topics are `ignored`. Rows are deleted after `WEBHOOK_RETENTION` (30 days).

## 21. Pagination

Default:
- page_size 50
- maximum 100

Cursor pagination should be used for high-volume event/reporting endpoints where appropriate.

## 22. Rate Limiting

Apply limits by:
- authenticated user,
- organization,
- IP where appropriate,
- endpoint class.

External provider rate limits must be respected separately.

## 23. Idempotency

Require `Idempotency-Key` for:
- campaign creation,
- external mutation actions,
- billing operations where applicable.

Store key + organization + request fingerprint + result.

## 24. Authorization Matrix

MVP authorization is organization-level (A7): membership + organization role + resource linked to the organization. Resource-level permissions (per store / per ad account) are a future extension; `authorize(context, action, resource)` already receives the resource. "Configurable" cells default to **No** until a decision enables them.

At minimum:

| Capability | Owner | Admin | Manager | Analyst | Viewer |
|---|---:|---:|---:|---:|---:|
| View analytics | Yes | Yes | Yes | Yes | Yes |
| View products | Yes | Yes | Yes | Yes | Yes |
| Manage connections and resource links | Yes | Yes | Yes | No | No |
| Generate AI strategy | Yes | Yes | Yes | Yes | No |
| Create campaigns | Yes | Yes | Yes | No | No |
| Approve AI actions | Yes | Yes | Yes | No | No |
| Enable autopilot | Yes | Yes | No/Configurable | No | No |
| Manage members and invitations | Yes | Yes | No | No | No |
| View audit log | Yes | Yes | No | No | No |
| Billing | Yes | No/Configurable | No | No | No |

## 25. API Versioning

Breaking changes require a new API version.

Provider API versions must be isolated inside connectors and documented separately.

## 26. API Testing Requirements

Every endpoint needs tests for:
- valid request,
- invalid request,
- authentication failure,
- authorization failure,
- wrong-tenant access,
- not found,
- provider failure where relevant,
- idempotent retry where relevant.

## 27. Security Requirement

Never trust:
- organization_id from the URL,
- product IDs,
- campaign IDs,
- provider IDs,
- AI-generated IDs,
- client-provided role/permission claims.

Resolve and authorize every resource server-side.
