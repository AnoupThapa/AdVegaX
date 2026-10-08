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

## 5. External Connections and Resources (Phase 1B framework; providers from Phase 2A)

Approved model A6: connection (authorization) → discovered resources → explicit organization links.

### GET /organizations/{organization_id}/connections
List connections with status and health; never secrets.

### POST /organizations/{organization_id}/connections/{provider}/start
Start the provider's authorization flow; returns the redirect URL. State is single-use and bound to user + organization + provider.

### GET /connections/{provider}/callback
Provider callback. Organization comes only from validated state. Environment-specific URL.

### GET /organizations/{organization_id}/connections/{connection_id}
### POST /organizations/{organization_id}/connections/{connection_id}/disconnect
Revokes credentials where the provider supports it; links are ended with history kept.

### GET /organizations/{organization_id}/connections/{connection_id}/resources
Resources discovered through the connection (not yet linked unless shown).

### POST /organizations/{organization_id}/resources/{resource_id}/link
### POST /organizations/{organization_id}/resources/{resource_id}/unlink
Explicit linking/unlinking; audited; history kept.

### POST /organizations/{organization_id}/resources/{resource_id}/sync
Queue synchronization of a linked resource.

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

Filters:
- actor
- action
- resource
- date range
- result

Never expose secret fields.

## 19. Billing

### GET /organizations/{organization_id}/billing

### POST /organizations/{organization_id}/billing/checkout

### POST /organizations/{organization_id}/billing/change-plan

### POST /organizations/{organization_id}/billing/cancel

### POST /billing/webhooks/provider

Billing webhooks must be signature-verified and idempotent.

## 20. Webhooks

Provider webhooks must:
- verify authenticity,
- resolve tenant safely,
- record event ID,
- enforce idempotency,
- queue processing,
- acknowledge quickly,
- retry failed internal processing.

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
