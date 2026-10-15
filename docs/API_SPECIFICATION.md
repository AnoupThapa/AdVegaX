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
| `GET /organizations/{organization_id}/connections` | 200 list `ConnectionOut` | Status, scopes, account label, last error code — never secrets |
| `POST /organizations/{organization_id}/connections/{provider}/start` | 200 `{authorize_url, expires_in_seconds}` | Creates single-use state (Redis, `CONNECT_STATE_TTL`) bound to user + organization + provider + PKCE verifier + validated connect parameters. **Optional body (2A-03):** `{"params": {…}}` (≤ 5 keys, values ≤ 255 chars), validated by the provider — Shopify requires `{"shop_domain": "eve-zone"}` (also accepts `eve-zone.myshopify.com` or a pasted store URL); **WooCommerce (2B-04)** requires `{"store_url": "shop.example.com/store"}` (normalized: HTTPS, public name, optional sub-folder) and first checks that the address answers with a WooCommerce REST API — **422 `STORE_NOT_REACHABLE`** with `details: [{"reason": <code>}]` otherwise (e.g. `woocommerce_api_not_found`, `retryable`, `store_redirected`); its `authorize_url` is the store's own `/wc-auth/v1/authorize` page (scope `read`). Other providers refuse any parameter. Errors: 422 `INVALID_CONNECT_PARAMS`; **409 `ACCOUNT_IN_USE`** when the platform account (e.g. the store) is live in another organization (Q6) |
| `GET /connections/{provider}/callback` | 303 → `APP_BASE_URL/connections?status=…` | Organization comes **only** from the validated state. `status=connected&organization_id=…&connection_id=…`, `status=cancelled&organization_id=…`, or `status=error&code=` `invalid_state` / `session_mismatch` / `not_permitted` / provider error code. `organization_id` is included only after the state is validated and the signed-in user is confirmed as a manager of that organization (cancelled, provider error, connected) — never for `invalid_state`, `session_mismatch` or `not_permitted` (1C-03). **2A-03:** the one-live-connection rule is checked **before** the token exchange (`code=account_in_use`); Shopify adds `invalid_signature`, `account_mismatch`, `missing_scopes`, `invalid_connect_params`. Reconnecting the same platform account from the same organization **reuses** the existing connection (`connection.reconnected` in the audit log). Hidden from OpenAPI |
| `POST /connections/{provider}/credentials` | 200 `{"status": "accepted"}` | **2B-04.** Platforms with key delivery (WooCommerce) post the generated key here, server to server: **no session or CSRF** (exact path exempt), JSON ≤ 4 KB, `THROTTLE_KEY_DELIVERY_PER_IP_PER_MINUTE` (30). Authenticated by the single-use connect state echoed as `user_id` (consumed at once). Only a `read` key is accepted, and it is verified against the store recorded at start before it is stored. Any failure: **422 `INVALID_KEY_DELIVERY`**, nothing echoed. The outcome is kept for `CONNECT_STATE_TTL` for the browser's return. Hidden from OpenAPI |
| `GET /connections/{provider}/callback` (key delivery) | 303 → `APP_BASE_URL/connections?status=…` | **2B-04.** For key-delivery platforms the callback is the browser's return (`success`, `user_id`): it shows the delivered outcome once, only to the same signed-in person — `connected`, `cancelled` (merchant declined; the state is retired), or `error` with `key_not_delivered`, `not_read_only`, `key_rejected`, `auth_header_stripped`, `woocommerce_too_old`, `account_in_use`, `not_permitted`, `session_mismatch`, `invalid_state` |
| `GET /organizations/{organization_id}/stores[/{store_id}]` (2B-06 additions) | `StoreOut` | New optional fields for self-hosted stores: `site_url`, `platform_version`, `health: {code, checked_at}` (code: `woocommerce_too_old` / `timezone_unknown` / `cost_of_goods_off`, or a provider error code when the daily check itself failed; `null` = fine), `counted_statuses` (order statuses the figures count). Empty for Shopify |
| `GET /connections/{provider}/install` | 303 → `APP_BASE_URL/connect/{provider}?account=…` or `APP_BASE_URL/connections?status=error&code=…` | **2A-03.** Platform-initiated install (Shopify install link; later the App Store). Public, signature-verified (HMAC + timestamp ≤ `SHOPIFY_INSTALL_MAX_AGE`), stores nothing: the web app then asks the person to sign in and choose the organization, which starts the normal state-protected flow. Errors: `invalid_signature`, `invalid_connect_params`, `unsupported`, `unknown_provider`. Hidden from OpenAPI |
| `GET /organizations/{organization_id}/connections/{connection_id}` | 200 `ConnectionOut` | |
| `POST /organizations/{organization_id}/connections/{connection_id}/disconnect` | 200 `ConnectionOut` | Revokes at the provider where supported (failure tolerated and recorded), erases ciphertext, ends active links (`connection_revoked`), status `revoked` |
| `POST /organizations/{organization_id}/connections/{connection_id}/rediscover` | 202 `JobOut` | Queues a discovery job |
| `GET /organizations/{organization_id}/connections/{connection_id}/resources` | 200 list `ResourceOut` | Includes capabilities, `linked`, `link_id`, `last_synced_at` |
| `POST /organizations/{organization_id}/resources/{resource_id}/link` | 201 `LinkOut` | Explicit; audited |
| `POST /organizations/{organization_id}/resources/{resource_id}/unlink` | 200 `LinkOut` | History kept (`unlink_reason=user`) |
| `GET /organizations/{organization_id}/resources/{resource_id}/links` | 200 list `LinkOut` | Link history |
| `POST /organizations/{organization_id}/resources/{resource_id}/sync` | 202 `JobOut` | Resource must be actively linked |
| `GET /organizations/{organization_id}/jobs/{job_id}` | 200 `JobOut` | Status, attempts, last error code |

**Error codes (Phase 1B):** `UNKNOWN_PROVIDER` 404 · (2B-04) `STORE_NOT_REACHABLE` 422 · `INVALID_KEY_DELIVERY` 422 · `CONNECTION_NOT_ACTIVE` 409 · `RESOURCE_NOT_LINKABLE` 409 · `ALREADY_LINKED` 409 · `NOT_LINKED` 409 (plus the Phase 1A codes, e.g. `FORBIDDEN`, `NOT_FOUND`, `SERVICE_UNAVAILABLE` when Redis is unavailable for connect state).

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

### GET /organizations/{organization_id}/creatives

### POST /organizations/{organization_id}/creatives

### PATCH /organizations/{organization_id}/creatives/{creative_id}

### POST /organizations/{organization_id}/creatives/{creative_id}/approve

### POST /organizations/{organization_id}/creatives/{creative_id}/reject

Approval must be recorded in audit history.

## 11. AI Strategy

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
| `GET /stores/{store_id}/metrics/daily?from&to` | all members | Default the last 30 store-local days; at most `METRICS_MAX_DAYS`. `definition_version` (`finance-v1`), `synced_from` (first fully covered day), per-day components and `cogs` / `gross_profit` / `cost_coverage` figures; days before `synced_from`, before the first import or in the future are `not_synchronized` (values null). `totals` adds `gross_margin`, `shipping_cost`, `payment_fees`, `new_vs_returning`; totals are `not_synchronized` if any day in the period is |

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
