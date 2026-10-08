# AdVegaX — Architecture & Discovery Report

**Version:** 3.1 — **APPROVED** by the product owner (2026-10-08); Phase 0 closed
**Date:** 2026-10-08
**Status:** Approved. Approval record A1–A14 in `MASTER_SPECIFICATION.md §21`. No application code, migrations, integrations or AI functionality exist. Phase 1A begins only after its implementation plan (`phases/PHASE_01A_PLAN.md`) is approved.
**Supersedes:** v1 (Shopify-first) and v2 (incomplete decision set).
**Decision basis:** Product-owner decisions D1–D22, recorded in `MASTER_SPECIFICATION.md §20`.

> **[VERIFIED 2026-10-08]** = checked against official documentation on this date; re-verify at phase start. **[VERIFY]** = not yet confirmed from official documentation. Neither is an API contract.

---

## Contents

1. Changes made in this round
2. Updated architecture understanding
3. Contradictions with existing specifications
4. Architectural consequences of platform independence
5. Provider abstraction strategy — review
6. Normalized data model — review
7. Tenant architecture — review
8. Authentication — review
9. Row-Level Security — review
10. Integration architecture — review
11. AI, financial and funnel architecture — summary
12. Risks and severity
13. Implementation sequence (vs D20)
14. Remaining decisions — blocking and non-blocking
15. Exact next step
16. Phase 0 closure — final consistency and architecture review

---

## 1. Changes made in this round (documentation only)

| File | Change |
|---|---|
| `MASTER_SPECIFICATION.md` | v1.3. §20 now holds the complete decision set D1–D22. The "pending reconfirmation" block was removed, because D11–D15 confirm it. §6 funnel no longer lists `refund` as a stage; revenue → profit are financial outcomes (D18). §7 adds **margins** and **budget utilization** (D17). §9 pipeline now starts with **Data → Deterministic Analytics → AI Context** (D16). |
| `ARCHITECTURE.md` | §12 AI: platform-independent pipeline; context only from normalized data; LLM gets no tools (D16). |
| `DATABASE_SCHEMA.md` | `funnel_daily.refunds` removed (D18). Refunds remain in `financial_daily`. |
| `DISCOVERY_REPORT.md` | This version. |
| `ROADMAP.md`, `PROJECT_STATUS.md`, `phases/PHASE_00…` | Updated to match. |

Earlier rounds already did the following: moved specs to `docs/`; renamed everything to AdVegaX; added provider architecture, WooCommerce in the MVP, session-cookie authentication, required RLS, environment-configured domains and CORS; retired `/auth/refresh`.

---

## 2. Updated architecture understanding

**AdVegaX is the central intelligence and orchestration layer.** Commerce, advertising and analytics platforms are interchangeable data sources and action targets behind provider interfaces. Shopify is one integration, not the foundation (D22). A merchant can use AdVegaX with WooCommerce only, or with only ad accounts connected.

```text
                         ┌────────────────────── AdVegaX core (platform-independent, D19) ──────────────────────┐
 Browser ─HTTPS─► app.*  │ Identity · Organizations · Membership · RBAC · Audit · Notifications · Billing       │
 (session cookie) api.* ─►│ Core product model (normalized) · Reporting · Financial engine · Funnel engine        │
                         │ AI (context → LLM → validation) · Recommendations · Optimization · Action Engine     │
                         └──────────────────────────────▲───────────────────────────────┬───────────────────────┘
                                                        │ normalized models only         │ typed actions only
                         ┌──────────────────────────────┴───────────────────────────────▼───────────────────────┐
                         │ Provider layer (only place platform-specific code exists)                            │
                         │ Commerce: Shopify · WooCommerce │ Advertising: Google Ads · Meta │ Analytics: GA4    │
                         └──────────────────────────────────────────────────────────────────────────────────────┘
 PostgreSQL (RLS) · Redis · Celery workers + scheduler · object storage · secret store / KMS (vendor-neutral)
```

| Area | Understanding after D1–D22 |
|---|---|
| Product | Independent multi-tenant SaaS; optimizes **profitable** growth, not clicks or ROAS alone (D3, D22) |
| Journey | Website → AdVegaX account → organization → connect commerce → connect ads → connect analytics → unified view → AI strategy, analytics, optimization (D2) |
| Tenancy | Organization = tenant. User → Membership → Organization → stores/accounts/integrations/data. Multi-org users "in the future", designed for now (D11) |
| Isolation | Authentication → authorization → tenant context → repository controls → RLS → database (D12) |
| Auth | AdVegaX server-side sessions; separate from platform authorization (D7, D10) |
| Integrations | MVP: Shopify, WooCommerce, Google Ads, Meta, GA4. Future: any platform via provider interfaces (D4, D5) |
| Credentials | Env vars in development, managed secret store in production, encrypted persistent tokens, separate per environment, never to frontend or LLM (D15) |
| AI | Reasons over normalized data and deterministic analytics only. No execution, no tools (D16) |
| Finance | Deterministic engine for revenue, refunds, discounts, spend, CPA, ROAS, product cost, gross and contribution profit, margins, CAC, budget utilization (D17) |
| Funnel | Impression → Purchase as stages; Revenue → Profit as financial outcomes; only where data permits (D18) |
| Engineering | Commercial production SaaS from day one; modular monolith (D21) |

---

## 3. Contradictions with existing specifications

### Resolved in specs (this round and earlier)

| # | Contradiction | Resolution |
|---|---|---|
| R1 | Old product name | Renamed |
| R2 | Specs at repo root | Moved to `docs/` |
| R3 | "Shopify is the financial source of truth" | Each store's own commerce platform is its source of truth |
| R4 | WooCommerce "planned" | MVP |
| R5 | `/auth/refresh` vs session cookies | Marked not used |
| R6 | RLS "consider" | Required (D12) |
| R7 | `refund` as a funnel stage (was C2) | Removed from stages (D18) |
| R8 | Financial list missing margins and budget utilization | Added (D17) |
| R9 | AI pipeline started at "AI recommendation" | Starts at Data → Deterministic Analytics → AI Context (D16) |

### Still open — need approval to amend

| # | Contradiction / gap | Proposal | Severity |
|---|---|---|---|
| **C3** | Architecture §3 shows both top-level `models/ schemas/ services/` and `domains/<x>/`. Master §18 and Architecture §3 list different domains. | Domain-first layout (§5.6). Domains: identity, organizations, integrations, commerce, advertising, analytics, funnel, finance, ai, strategy, creatives, recommendations, actions, automation, audit, billing, notifications, reporting. | MEDIUM — blocks Phase 1 |
| **C4** | Schema omits tables other specs require: idempotency keys, webhook events, sync runs, OAuth/connect state, invitations, verification/reset tokens, approvals, strategies, plans/entitlements, cost history, FX rates, customer refs, refunds, account links. | Add as spec amendments (§6). | MEDIUM — Phase 1 subset blocks Phase 1 |
| **C5** | `financial_daily.roas`, `.cpa` and `products.margin_percent` are stored. That conflicts with D17's centralized deterministic calculation, and ratios can't be aggregated. | Store additive components; compute ratios, margins and budget utilization on read. | MEDIUM |
| **C6** | `analytics_events` assumes event-level GA4 data. [VERIFY] The GA4 Data API returns aggregates. Property discovery needs the **GA4 Admin API**, which isn't listed. | `analytics_daily` + add GA4 Admin API (read-only). | MEDIUM — blocks Phase 5 |
| **C7 (new)** | `integrations` has a single `external_account_id`. In practice one Google or Meta authorization can reach **many** ad accounts, and a GA4 grant many properties, while Shopify and WooCommerce are one store per connection. | Split **connections** (who authorized what, holding the credentials) from **connected accounts** (stores, ad accounts, properties the org chose to link). See §6.2. | HIGH — shapes Phase 1 schema |
| **C8 (new)** | D12 requires "**platform-account permissions**", but RBAC (Master §12, API §24) is organization-level only. | Phase 1: permission API takes `(user, org, action, resource)`, so resource-scoped grants can be added later. MVP enforces org roles plus "only accounts linked to this org". Per-account grants for specific users come later. | MEDIUM — needs a decision (Q4) |
| **C9 (new)** | D19 says **billing** must not be platform-specific. [VERIFIED 2026-10-08] Shopify App Store apps must use Shopify's billing for app charges. | Only relevant if a Shopify App Store channel is added later. Keep a billing-provider interface (Stripe first), and don't build Shopify billing in MVP. | LOW now |
| **C10 (new)** | Shopify connection mechanics: connecting many unrelated stores requires a **public** Shopify app, which needs Shopify approval [VERIFIED 2026-10-08]. Public apps are subject to App Store requirements (install from Shopify surfaces, no manual shop-URL entry, embedding). | Core stays independent (D22). The Shopify *connector* follows Shopify's rules; development stores need no approval. Confirm requirements with Shopify Partner Support before production. | HIGH for production Shopify; not Phase 1 |

---

## 4. Architectural consequences of platform independence

1. **No platform owns identity.** AdVegaX must run the full account lifecycle itself: sign-up, email verification, password reset, abuse protection, MFA readiness, session security. **Transactional email delivery** becomes a Phase 1 dependency, behind a vendor-neutral interface.
2. **The core speaks only the normalized model.** Every provider maps into AdVegaX entities at the provider boundary. Money, IDs, time zones and statuses are converted there, never in the core.
3. **Capabilities differ, so the core must handle absence.** WooCommerce may lack product cost; some stores lack GA4 ecommerce tagging; not every provider has webhooks or a validate-only mode. Each provider declares capabilities, and the core shows "not available" instead of zero or guesses.
4. **Mixed portfolios are normal.** One organization may have a Shopify store, a WooCommerce store, two Google Ads accounts and one Meta account, in different currencies and time zones. Reporting needs an organization reporting currency and time zone, FX rates, and explicit store ↔ ad account ↔ property links.
5. **Each store is its own financial source of truth.** Cross-store totals are aggregations of per-store truths. No cross-platform product or customer unification in MVP (same SKU on two stores = two products).
6. **Attribution can't rely on any one platform.** AdVegaX needs its own conventions: UTM parameters on campaigns it builds (Phase 10B), and platform-reported vs blended metrics kept separate.
7. **Generic sync engine.** Webhooks where a provider supports them, polling and reconciliation everywhere, a look-back window for restated data, and one job/sync-run model for all providers.
8. **Self-hosted commerce widens the attack surface.** WooCommerce means AdVegaX calls merchant-supplied URLs. SSRF protection becomes a Phase 1 platform service, not a Phase 2 afterthought.
9. **A useful empty state.** A user with nothing connected must still see a working product: onboarding checklist, organization, members.
10. **Future Shopify App Store channel = an entry surface.** If built, it links a Shopify installation to an AdVegaX organization and never replaces AdVegaX login (D6). The connection model in §6.2 already supports this.
11. **Testing scales by provider.** Each provider needs contract tests against recorded fixtures, plus **parity tests** proving equivalent Shopify and WooCommerce data produce identical normalized records and financial results.
12. **Support and documentation burden grows.** Per-provider setup guides, health status and error messages that merchants can act on.

---

## 5. Provider abstraction strategy — review

### 5.1 Interfaces (by category)

```text
CommerceProvider        ShopifyProvider, WooCommerceProvider           (future: BigCommerce, Adobe Commerce, custom, Amazon Seller)
AdvertisingProvider     GoogleAdsProvider, MetaAdsProvider             (future: TikTok, Microsoft, Amazon, LinkedIn)
AnalyticsProvider       GA4Provider                                    (future analytics)
(future) MarketingProvider, PaymentsDataProvider                       (Klaviyo, Mailchimp, HubSpot; payment-data integrations)
BillingProvider         StripeBilling (AdVegaX's own subscriptions — separate from payment-data integrations)
```

### 5.2 Contract each provider implements

| Concern | Contract |
|---|---|
| Identity | `provider_code`, provider API version (pinned) |
| Capabilities | Declared flags, e.g. `webhooks`, `product_cost`, `inventory`, `refund_lines`, `presentment_currency`, `validate_only`, `create_campaign`, `ecommerce_events` |
| Connection | `start_connect(state)`, `complete_connect(callback)`, `refresh_credentials()`, `revoke()`, `health_check()` |
| Discovery | `list_accounts(connection)` → stores / ad accounts / properties available to link |
| Read | Paged, cursor-based fetchers returning **normalized DTOs** plus a raw-payload reference |
| Incremental | `parse_webhook(request)` (verified) or `changes_since(cursor)` |
| Write (Phase 10A+) | Only typed action handlers called by the Action Engine; none exposed elsewhere |
| Errors | Classified: `retryable`, `rate_limited(retry_after)`, `auth_expired`, `permission_denied`, `not_found`, `invalid_request`, `unknown_outcome` |
| Limits | Declares rate-limit buckets so a shared limiter can schedule fairly across tenants |

### 5.3 Rules

- Provider code lives only in `providers/<category>/<name>/`. Core domains import interfaces and normalized models, never provider SDK types.
- Units, IDs, time zones and statuses are converted in the provider mapper.
- A provider registry resolves `provider_code` → implementation + capabilities. Adding a provider is additive.
- Each provider has its own `docs/INTEGRATION_GUIDES.md` section with verified facts and the date checked.
- No browser automation; official APIs only (PROJECT_RULES §2).

### 5.4 Risks in the abstraction

| Risk | Mitigation |
|---|---|
| Lowest-common-denominator model hides useful platform features | Core model + capability flags + a typed `provider_extensions` area that the core may *display* but never compute on |
| Leaky abstraction (Shopify concepts drift into core) | Design the normalized model against **two** commerce providers from the start; parity tests; code-review rule |
| Over-engineering for platforms that don't exist yet | Interfaces only for categories in MVP; future categories added when needed |

### 5.5 Advertising-specific normalization

Google "ad group" and Meta "ad set" both map to normalized `AdGroup`. Budgets carry `level` (campaign / ad group), `type` (daily / lifetime / shared) and `amount` (Decimal + currency). Google micros and Meta minor units are converted in the mapper. [VERIFY] at phase start.

### 5.6 Recommended layout (supports C3)

```text
backend/app/
├── core/  db/  api/                     # cross-cutting
├── domains/<domain>/                    # models, schemas, repository, service, router, permissions
├── providers/
│   ├── base/                            # interfaces, capabilities, registry, normalized DTOs, error taxonomy
│   ├── http/                            # SSRF-safe client, rate limiter, retry policy
│   ├── commerce/{shopify,woocommerce}/
│   ├── advertising/{google_ads,meta}/
│   ├── analytics/{ga4}/
│   └── billing/{stripe}/
├── webhooks/                            # verified ingestion → webhook_events → queue
└── workers/                             # Celery app, scheduler, sync orchestration
```

---

## 6. Normalized data model — review

### 6.1 Cross-cutting conventions

| Convention | Rule |
|---|---|
| Keys | UUID primary keys; `organization_id` on **every** tenant-owned table; composite FKs `(organization_id, parent_id)` |
| External identity | `provider`, `external_id` stored as **text** (Shopify GIDs, Woo integers, Google int64, Meta strings), unique per `(organization_id, connected_account_id, external_id)` |
| Sync metadata | `external_updated_at`, `synced_at`, `sync_run_id`, `raw_payload_ref` |
| Money | `Decimal` amount + ISO-4217 currency. Never float. Never mixed currencies in one sum without FX. |
| Time | UTC timestamps + source time zone where it affects day boundaries |
| Lifecycle | `created_at`, `updated_at`, `deleted_at` (soft delete where history matters) |
| Derived values | Not stored as ratios; computed by the finance or analytics module |

### 6.2 Connections vs connected accounts (C7)

```text
Organization
 └── Connection            (provider, auth_scheme, status, scopes, connected_by_user_id, credentials → encrypted)
      └── ConnectedAccount (kind: store | ad_account | analytics_property; external_id; name; currency; timezone; status)
```

- Shopify / WooCommerce: 1 connection → 1 store.
- Google Ads / Meta: 1 connection → many ad accounts (the user picks which to link).
- GA4: 1 connection → many properties.
- **Credential durability:** a Google/Meta grant belongs to the person who authorized it. If they leave the organization, access may break. Record `connected_by`, monitor health, support reconnect. [VERIFY] Meta system-user tokens as a more durable option.

### 6.3 Canonical entities (MVP)

| Domain | Entities |
|---|---|
| Identity / tenancy | User, Session, AuthFactor (MFA-ready), EmailVerification, PasswordReset, Organization, Membership, Invitation, (designed) AgencyGrant |
| Integrations | Connection, ConnectionCredential, ConnectedAccount, ConnectState, SyncRun, WebhookEvent, RawPayloadRef |
| Commerce | Store (= ConnectedAccount of kind store, plus store settings), Product, Variant, InventoryLevel, ProductCostHistory, Order, OrderLine, Refund, RefundLine, CustomerRef (hashed) |
| Advertising | AdAccount (= ConnectedAccount), Campaign, AdGroup, Ad, CreativeRef, Budget, PerformanceDaily (per level) |
| Analytics | AnalyticsProperty (= ConnectedAccount), AnalyticsDaily (date × dimensions × metrics) |
| Linking | StoreAdAccountLink, StoreAnalyticsLink |
| Finance | FxRate, MetricDefinition (versioned), FinancialDaily (additive components), StoreCostRules (shipping/fee rules) |
| Funnel | FunnelDaily (stages with per-stage source) |
| AI | AiModel, PromptVersion, AiRun, CampaignStrategy, Creative (+ versions), Recommendation |
| Actions | Action, Approval, IdempotencyKey, AutomationPolicy (per org / account / campaign / action class) |
| Platform | AuditLog, SecurityEvent, Notification, Plan, Entitlement, UsageRecord, BillingCustomer, Subscription, Invoice |

### 6.4 Provider mapping preview — to verify at each phase start

| Normalized | Shopify | WooCommerce | Google Ads | Meta | GA4 |
|---|---|---|---|---|---|
| Store / account | Shop | Site | Customer (account) | Ad account | Property |
| Product / Variant | Product / ProductVariant | Product / Variation | — | — | item dimensions |
| Order / OrderLine | Order / LineItem | Order / line_items | — | — | — |
| Refund | Refund | Order refund | — | — | — |
| Product cost | InventoryItem cost [VERIFY] | Native COGS or plugin [VERIFY] | — | — | — |
| Campaign / AdGroup / Ad | — | — | Campaign / AdGroup / AdGroupAd | Campaign / AdSet / Ad | — |
| PerformanceDaily | — | — | metrics by segments.date | Insights by day | — |
| AnalyticsDaily | — | — | — | — | Report rows by date |

### 6.5 Model gaps to close before the dependent phase

- **Phase 1:** connection/connected-account split; invitations; tokens; audit; idempotency; job runs; MFA-ready factor table.
- **Phase 2:** cost history, refunds, customer refs, webhook events, sync runs, raw payload refs.
- **Phase 6:** FX, links, metric definitions, cost rules.
- **Phases 8–10:** strategies, approvals.
- **Phase 13:** plans, entitlements, usage.

---

## 7. Tenant architecture — review

| Requirement (D11, D12) | Design |
|---|---|
| Tenant = organization | Every tenant-owned row carries `organization_id`. Composite FKs make cross-org references impossible. |
| Multi-org users "in the future" | Schema supports many memberships **now**. The UI can start with one, plus an org switcher when needed. Retrofitting would be costly. |
| Never trust client tenant identity | `organization_id` in the URL is only a *claim*. Server resolves session → user → active membership in that org → role → `TenantContext`. No membership → 404, which doesn't reveal the org exists. |
| Server-side authorization always | Central `authorize(context, action, resource)` called by services, deny by default. Route-level checks alone are not enough. |
| Resource-level authorization | Every resource ID (product, campaign, account, AI-suggested ID) is re-loaded **within the tenant** before use |
| Platform-account permissions (C8) | MVP: org role + "account must be linked to this org". Later: optional per-user grants on connected accounts. |
| Workers / webhooks | Tasks carry `organization_id`; worker sets context per transaction. Webhooks resolve the tenant from a *verified* provider identity. |
| Caches / files | Cache keys and object-storage paths prefixed with org ID; signed URLs scoped per tenant |
| Same external account in two orgs | Technically possible (unique keys are per org). **Policy decision** (Q6), relevant to agencies. |
| Agency (Phase 14) | Explicit, audited, revocable grants from client org to agency org. Designed in Phase 1, built in Phase 14. |

---

## 8. Authentication — review

| Area | Design (D7, D10, D15) |
|---|---|
| Separation | **AdVegaX identity domain** (users, sessions, memberships, roles) vs **platform authorization domain** (connections, encrypted credentials). Platform tokens never authenticate a user, never reach the browser, never reach the LLM. |
| Session | Opaque random ID in `HttpOnly`, `Secure` (production), `SameSite=Lax` cookie scoped to the API host; only a hash stored; idle and absolute expiry; rotation on login and privilege change; revoke one / revoke all; logout |
| Cross-subdomain | `app.` and `api.` share a registrable domain, so the cookie is same-site and works with `SameSite=Lax`. Requests use `credentials: include`. CORS allowlists the exact `app.` origin with credentials, never `*`. |
| CSRF | Required for all state-changing requests: synchronizer or double-submit token in a header, plus Origin/Referer checks |
| Passwords (if used) | Argon2id; breached-password check optional; throttling per IP and per account; uniform responses (no account enumeration) |
| Account recovery | Single-use, hashed, short-lived email tokens; all sessions revoked on reset |
| MFA-ready | Factor table and "step-up required" flag designed now; TOTP or passkeys enabled later |
| Auditing | Login success/failure, logout, password change/reset, session revocation, MFA changes, membership/role changes |
| Email | Transactional email interface (SMTP in development; provider chosen with hosting) |
| Local development | Same mechanism on `localhost` with `Secure` relaxed only in the development environment via configuration |
| **Open** | MVP login methods (Q3): email + password only, or also Google sign-in / magic link |

---

## 9. Row-Level Security — review (D12 checklist)

| D12 item | Design |
|---|---|
| Layering | Auth → app authorization → `TenantContext` → repositories require context → RLS policies → DB |
| **Connection pooling** | Tenant ID set with transaction-local `SET LOCAL app.current_org_id` (or `set_config(..., true)`) at the start of each transaction, so it can't survive into the next pooled use. With a PgBouncer-style pooler, transaction pooling is compatible because the setting is transaction-scoped. Session-level `SET` is forbidden. |
| **Transaction-scoped context** | Unit-of-work wrapper opens a transaction, sets context, runs, commits. Repositories refuse to run without a context. Policies use `current_setting('app.current_org_id', true)` and **fail closed** (no rows) when it's unset. |
| **Background workers** | Every task payload includes `organization_id`. The task opens its own unit of work with that context and re-checks resource ownership. |
| **Celery tasks** | Base task class enforces the above; correlation ID propagated; idempotent by design; DB `job_runs` is the source of truth |
| **Scheduled jobs** | Scheduler runs as `advegax_system` only to *enumerate* due work (e.g. which connections need sync) and enqueues per-tenant tasks. It doesn't process tenant data cross-tenant. Single-instance scheduler lock. |
| **Migrations** | Run as `advegax_migrator` (schema owner) in a separate deploy step. Every new tenant table must include its RLS policy in the same migration (CI check). |
| **Administrative operations** | No staff cross-tenant access in MVP. Later: time-boxed, audited, explicit grant, under a dedicated role. |
| **System-level operations** | Narrow `advegax_system` role, allowlisted operations only (scheduler enumeration, retention jobs). Every use audited. |
| **RLS bypass risks** | App role is not superuser, not table owner, no `BYPASSRLS`. Tables use `FORCE ROW LEVEL SECURITY`. No `SECURITY DEFINER` functions without review. Views use `security_invoker`. Backups and analytics exports handled outside the app role. |
| **Testing** | (a) Raw SQL as `advegax_app` with no context → zero rows on every tenant table. (b) Org A context never sees org B. (c) Every API route called with another org's resource IDs → 404. (d) Worker tasks with mismatched org/resource → rejected. (e) CI fails if a tenant table lacks a policy. |
| Performance | Index `organization_id` (leading column in composite indexes); keep policies simple equality checks |

---

## 10. Integration architecture — review

| Element | Design |
|---|---|
| Connect flows | Generic `ConnectState`: single-use nonce bound to user + org + provider (+ PKCE where supported), short TTL. The callback derives the org from state only. Environment-specific callback URLs (D13). |
| Credential storage | Envelope encryption via a vendor-neutral KMS interface; key versioning; decrypt only inside providers; separate provider apps and credentials per environment (D15) |
| Token lifecycle | Background refresh with **per-connection distributed lock**. [VERIFIED 2026-10-08] Shopify's expiring offline tokens (1 h access, 90-day rotating refresh) must not be refreshed concurrently. Revocation and expiry surfaced as connection health. |
| Sync engine | `SyncRun` per connected account and data type; cursor/checkpoint; backfill → incremental → reconciliation; look-back re-sync for ad and analytics restatement |
| Webhooks | Verify signature (Shopify HMAC; WooCommerce signature [VERIFY]), persist `WebhookEvent` (dedupe by provider event ID), acknowledge fast, process async, reconcile periodically |
| Outbound HTTP | One SSRF-safe client for all providers (critical for WooCommerce), per-provider/per-account rate limiters, retry with backoff and jitter, error taxonomy |
| Writes | Only via Action Engine (Phase 10A): paused-first, idempotent, unknown-outcome reconciliation |
| Versioning | Provider API versions pinned per provider; sunset calendar in `INTEGRATION_GUIDES.md` |
| Test strategy | Recorded fixtures (no live calls in CI), contract tests per provider, parity tests across commerce providers, sandbox/test accounts for manual verification |
| Long-lead approvals | Shopify public app review, Google Ads developer token, Google OAuth verification, Meta App Review and Business Verification — start once a test app exists |

**Per-provider notes**

- **Shopify** [VERIFIED 2026-10-08]: GraphQL Admin API only for new public apps; expiring offline tokens; mandatory privacy webhooks (`customers/data_request`, `customers/redact`, `shop/redact`, the last sent 48 hours after uninstall); public distribution requires approval (C10).
- **WooCommerce** [VERIFIED 2026-10-08]: REST API v3 (WooCommerce 3.5+, WordPress 4.4+, pretty permalinks); HTTPS Basic auth with consumer key and secret; `/wc-auth/v1/authorize` posts the keys to an HTTPS callback, and the app chooses the `user_id` it echoes back. Use a single-use nonce for it, and request `read` scope only. [VERIFY] Webhook signature, native COGS.
- **Google Ads / Meta / GA4**: unchanged from v2. [VERIFY] at phase start, especially the GA4 Admin API, Google Ads Required Minimum Functionality, and Meta permissions.

---

## 11. AI, financial and funnel architecture — summary

- **AI (D16):** platform-independent; context built only from normalized data and deterministic analytics; no tools; schema-validated output; closed action catalogue; AI-referenced IDs re-resolved within the tenant; AI proposes intent and deterministic code computes amounts; prompt-injection defences for merchant- and platform-supplied text; per-org AI cost limits; evaluation sets.
- **Finance (D17):** one Decimal-based engine and a versioned metric-definition registry. Additive components stored; ratios, margins and budget utilization computed on read. Figures tagged with definition version, sources and freshness. **Metric definitions still need sign-off before Phase 2 finance work** (stop condition, PROJECT_RULES §18).
- **Funnel (D18):** stages Impression → Purchase, each with a declared source; Revenue → Profit from the finance engine; unavailable stages shown as unavailable; drop-off detection is deterministic and feeds AI later.

---

## 12. Risks and severity

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | Cross-tenant data leak | CRITICAL | Layered isolation (§7, §9); composite FKs; mandatory isolation tests |
| 2 | Duplicate campaign creation on retry | CRITICAL | Action Engine state machine; persist before call; reconcile unknown outcomes |
| 3 | Autopilot overspend / compounding budget changes | CRITICAL | Hard limits in deterministic code; cumulative limits; cooldowns; kill switch; [VERIFY] platform over-delivery |
| 4 | AI fabricates IDs or numbers, or is prompt-injected | CRITICAL | No tools; schema validation; resource re-resolution; deterministic amounts; human approval |
| 5 | Credential theft | CRITICAL | KMS envelope encryption; per-environment credentials; never to frontend or LLM; log scrubbing |
| 6 | **SSRF via merchant-supplied WooCommerce URLs** | CRITICAL | SSRF-safe client in Phase 1; DNS/IP checks; HTTPS only; redirect re-check |
| 7 | RLS bypass (owner role, pooled session settings, SECURITY DEFINER) | HIGH | Role design and tests (§9) |
| 8 | Leaky provider abstraction | HIGH | Two commerce providers in Phase 2; parity tests; capability model |
| 9 | Wrong financial figures | HIGH | Signed-off definitions; golden tests; source labelling |
| 10 | Double-counted conversions across sources | HIGH | Platform-reported and blended metrics kept separate |
| 11 | Ad and analytics data restatement | HIGH | Look-back re-sync and idempotent recompute |
| 12 | Partial execution of multi-step creates | HIGH | Paused-first; activate last; compensating actions |
| 13 | Duplicate or out-of-order webhooks | HIGH | WebhookEvent dedupe; reconciliation |
| 14 | Platform approvals delay launch | HIGH | Start applications early; read-only first |
| 15 | Shopify public-app requirements (C10) | HIGH | Confirm with Shopify; connector-level compliance |
| 16 | Concurrent token refresh invalidates tokens | HIGH | Per-connection lock |
| 17 | Shared provider rate limits starve tenants | HIGH | Fair, per-account limiter and queue partitioning |
| 18 | Credential owner leaves organization | MEDIUM | `connected_by`, health checks, reconnect flow |
| 19 | Celery task loss or duplication; scheduler double-run | MEDIUM | DB job records, idempotent tasks, scheduler lock |
| 20 | Currency and time-zone mixing | MEDIUM | Reporting currency/time zone; FX table |
| 21 | Billing webhook drift | MEDIUM | Idempotent webhooks; nightly reconciliation |
| 22 | PII over-collection; LLM data exposure | MEDIUM | Hashed customer refs; LLM input allowlist |
| 23 | Observability gaps across async flows | MEDIUM | Correlation IDs end-to-end; metrics on provider, job and AI calls |
| 24 | Database growth | LOW (MVP) | Monthly partitions for high-volume tables |

---

## 13. Implementation sequence vs D20

Your sequence is kept. Two refinements have strong technical reasons, and neither changes the order:

| D20 phase | Refinement | Reason / dependency |
|---|---|---|
| 2 Commerce | Split into **2A Shopify** then **2B WooCommerce**, in that order | One provider at a time keeps changes small. Building WooCommerce straight after Shopify proves the normalized model and abstraction before analytics and AI depend on them. |
| 2 / 6 | **Finance core starts in Phase 2**, completed in Phase 6 | The commerce platform is the financial source of truth; profit (D17) must be validated as soon as order data exists |
| 10 Campaign Builder | Split into **10A Action Engine** then **10B Campaign Builder** | Every external mutation passes through the Action Engine (D16). It must exist and be tested before the first campaign creation. Phases 11–12 also depend on it. |
| — | **Phase 0** (approval) precedes Phase 1 | You required approval before implementation |
| 13 Billing | Entitlement **stub** in Phase 1 | Avoids retrofitting plan checks across every feature later |
| 14 Agency | Grant model **designed** in Phase 1 | Tenancy changes are the most expensive retrofit |

The dependency graph and per-phase plans are in `ROADMAP.md` and `phases/`.

---

## 14. Remaining decisions

### Previously blocking Phase 1 — all resolved by the Phase 0 approval

| # | Decision | Resolution |
|---|---|---|
| Q1 | Repository ownership and file operations | Product owner controls `advegax`; agent may create/modify/move/rename and conservatively delete files, Git authorized (A1). GitHub remote URL still to be shared (not blocking local work). |
| Q2 | Amendments C3, C4, C5, C7 | Approved (A3–A6) and applied |
| Q3 | MVP login methods | Email + password with verification; future IdPs/MFA/passkeys without redesign (A8) |
| Q4 | Platform-account permissions (C8) | Organization-level MVP; resource-level later without redesign (A7) |

### Future-phase decisions — not Phase 0 or Phase 1 blockers

| # | Decision | Needed by |
|---|---|---|
| Q5 | Shopify public-app approach; written confirmation from Shopify Partner Support (C10) | 2A production |
| Q6 | May the same store or ad account be connected to two organizations? | 2A |
| Q7 | Financial metric definitions v1 (net revenue, refunds timing, COGS source/missing-cost rule, shipping and fees, contribution profit, ROAS/CPA bases, CAC, attribution, FX source, reporting time zone, rounding) | 2A (store metrics), 6 |
| Q8 | Customer PII policy (recommended: hashed customer key only) | 2A |
| Q9 | Backfill depth and refresh frequency | 2A–5 |
| Q10 | WooCommerce minimum versions; HTTPS-only stores | 2B |
| Q11 | GA4 aggregated model + GA4 Admin API (C6) | 5 |
| Q12 | LLM provider and model; creative scope (copy only vs images) | 8, 9 |
| Q13 | Autopilot action classes and default limits | 12 |
| Q14 | Plans, pricing, trials, usage limits | 13 |
| Q15 | Agency model; retention periods; launch languages and currencies | 14 / staging |
| Q16 | Hosting provider and region; transactional email provider | First staging deployment |

**Resolved since v2:** the multi-tenancy text (D11), RLS (D12), domains (D13), credential rules (D14–D15), funnel stages (D18).

---

## 15. Exact next step

Phase 0 is closed. Next: the product owner reviews and approves `phases/PHASE_01A_PLAN.md` (platform core & identity). No Phase 1A code is written before that approval.

---

## 16. Phase 0 closure — final consistency and architecture review

### 16.1 Changes applied after approval

| Document | Changes |
|---|---|
| `MASTER_SPECIFICATION.md` (v1.4) | §21 Phase 0 approval record A1–A14; §3 Celery with DB job records; §5 explicit resource linking in the journey; §18 domain list aligned with the domain-first layout and phases; A7 clarifies how D12's "platform-account permissions" are met in MVP |
| `PROJECT_RULES.md` | §16.1 conservative file-deletion rules (A1); §16A platform-independence and data-integrity rules (D19, A5, A10–A13) |
| `ARCHITECTURE.md` | §3 approved domain-first structure with phase annotations; §6 user + organization context and global identity tables; §7 email + password, credential separation for future IdPs/MFA, transactional email outbox; §8 four-layer authorization model; §9.1 connection → resource → link model; §9.2 availability states; §9.3 SSRF requirements; §11 Campaign Builder only via Action Engine; §12 AI data boundary; decision references renumbered to D1–D22 |
| `DATABASE_SCHEMA.md` | §0 table-introduction-by-phase; Phase 1A identity/organization/session/audit/outbox tables; Phase 1B connection/resource/link/job tables; stores and ad accounts as resource extensions; `margin_percent`, `roas`, `cpa` removed; `analytics_events` marked as future decision Q11; §19 roles, context and table classes; §19A data availability |
| `API_SPECIFICATION.md` | Metric value object with availability; full Phase 1A auth/organization/invitation endpoints; connections/resources endpoints replacing `integrations`; organization-level matrix note and audit-log row |
| `ROADMAP.md`, `PROJECT_STATUS.md`, `phases/` | Phase 0 complete; Phase 1 split into 1A/1B/1C; Phase 1A plan added |

### 16.2 Consistency checks performed

| Check | Result |
|---|---|
| Previous working name anywhere in the repository | None |
| All 22 decisions present and numbered consistently (D1–D22); cross-references in ARCHITECTURE, DATABASE_SCHEMA, API_SPECIFICATION use current numbers | Pass (stale D5/D6/D7/D4 references from the earlier numbering corrected) |
| "Pending reconfirmation" language | Removed |
| Single-account `integrations` model / `integration_id` references | Removed; replaced by connection/resource/link model everywhere |
| `refund` as a funnel stage | Removed from MASTER §6 and `funnel_daily` |
| Stored ratios (`roas`, `cpa`, `margin_percent`) | Removed; A5 rule in schema, API and rules |
| Token-refresh endpoint vs sessions | Marked not used; session model consistent across ARCHITECTURE §7, API §3, MASTER D10/A8 |
| RLS described as optional anywhere | No; required in MASTER D12, ARCHITECTURE §6, DATABASE §19 |
| Shopify App Store as an MVP dependency anywhere | No; future channel only (D6, A14, ARCHITECTURE §7) |
| Action Engine numbering (former "9.5") | 10A everywhere; 10B uses it only |
| Domain lists (MASTER §18 vs ARCHITECTURE §3) | Aligned |
| Q5–Q16 | Marked future-phase decisions in this report, MASTER §21, PROJECT_STATUS |

### 16.3 Remaining known gaps (by design, not contradictions)

- `analytics_events` remains in the target schema with a Q11 notice until the Phase 5 decision.
- Exact Phase 1B schema for connections/resources/links is finalized in the 1B plan (A6).
- Financial metric definitions are still to be signed off before Phase 2A finance work (Q7).
- GitHub remote not yet created; the local repository is initialised and committed.

### 16.4 Architecture review conclusion

The specifications are internally consistent with D1–D22 and A1–A14. The platform-independent core, the connection/resource/link model, organization-level authorization with a resource-ready interface, layered tenant isolation with RLS, AdVegaX-owned identity with transactional email, explicit data availability, the SSRF boundary and the AI data boundary are all represented in the governing documents. Phase 0 is complete.

---

### Sources (verified 2026-10-08)

- [Shopify App Store requirements](https://shopify.dev/apps/store/requirements)
- [Shopify app distribution](https://shopify.dev/docs/apps/launch/distribution)
- [Shopify offline access tokens](https://shopify.dev/docs/apps/build/authentication-authorization/access-token-types/offline-access-tokens)
- [Shopify changelog — expiring offline tokens](https://shopify.dev/changelog/expiring-offline-access-tokens-required-for-all-public-apps-as-of-january-1-2027)
- [Shopify privacy law compliance](https://shopify.dev/docs/apps/build/compliance/privacy-law-compliance)
- [WooCommerce REST API documentation](https://woocommerce.github.io/woocommerce-rest-api-docs/)
