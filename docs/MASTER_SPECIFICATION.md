# AdVegaX — Master Product & System Specification

**Status:** Foundational specification  
**Version:** 1.4 (2026-10-08 — decisions D1–D22 and Phase 0 approval record in §20–§21)  
**Product type:** Independent, platform-independent multi-tenant SaaS web application / AI E-commerce Advertising & Growth Operating System

## 1. Product Vision

AdVegaX is a commercial SaaS platform that connects an e-commerce merchant's store, advertising platforms, analytics, product data, financial data, and AI into one controlled growth system.

The platform should understand the complete funnel:

Product → Marketing Strategy → Creative → Advertising → Impression → Click → Landing Page → Product View → Add to Cart → Checkout → Purchase → Revenue → Cost → Profit → Repeat Purchase.

The product is not merely an advertising dashboard. Its central purpose is **profitable, measurable, explainable growth** — optimizing for profitable business growth, not clicks, impressions or advertising ROAS alone. Over time it connects products, pricing, margins, inventory, marketing strategy, advertising, creatives, traffic, conversion, revenue, profitability, customer behavior and optimization.

AdVegaX is used directly through its own web application. It does not depend on any commerce platform (including Shopify) for authentication, architecture or distribution.

## 2. Initial Integrations

MVP (initial integrations only):
- Commerce: Shopify (GraphQL Admin API), WooCommerce (REST API)
- Advertising: Google Ads API, Meta Marketing API
- Analytics: Google Analytics 4 Data API

Possible future integrations (not MVP; added through provider interfaces without rewriting the core):
- Commerce: BigCommerce, Magento / Adobe Commerce, custom platforms, Amazon Seller, others
- Advertising: TikTok Ads, Microsoft Ads, Amazon Ads, LinkedIn Ads, others
- Marketing / CRM: Klaviyo, Mailchimp, HubSpot
- Payments / finance: Stripe and other payment providers

AdVegaX's own subscription billing (Stripe, Phase 13) is separate from any payment-provider *data* integration.

All third-party APIs must be implemented using current official documentation. The system must never invent unsupported API capabilities.

## 3. Technology Baseline

### Backend
- Python
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Redis
- Celery with Redis broker; database job records are the durable source of truth

### Frontend
- Next.js
- React
- TypeScript
- Responsive web UI

### Infrastructure
- Docker
- CI/CD
- Separate local/development/staging/production environments
- Centralized structured logging
- Error monitoring
- Metrics and health checks

## 4. Core Principles

1. Multi-tenant by design.
2. Tenant data must never leak across organizations.
3. OAuth and official APIs are mandatory for platform connections.
4. Credentials/tokens must be encrypted at rest.
5. Minimum required permissions/scopes only.
6. AI recommends; deterministic application logic validates and executes.
7. LLMs must never directly execute arbitrary code or financial/advertising actions.
8. Financial calculations are deterministic backend calculations.
9. Every external mutation is authorized, traceable, idempotent where possible, and auditable.
10. Human approval is required for campaign creation initially.
11. Autopilot must always respect hard budget and policy limits.
12. Do not use browser automation where an official API is available.
13. Do not silently guess when API behavior is uncertain.
14. Preserve working code; make targeted changes.
15. Security and reliability are product requirements, not later enhancements.

## 5. MVP User Journey

1. User creates account.
2. User creates/selects organization.
3. User connects a commerce platform (Shopify or WooCommerce in MVP).
4. Platform imports products, variants, inventory, orders and refunds.
5. User connects Google Ads.
6. User connects Meta Ads.
7. User connects GA4.
8. Platform discovers available accounts/properties; the user explicitly links the ones the organization will use.
9. User selects a product.
10. User enters objective, market, budget and constraints.
11. AI creates a structured strategy.
12. User reviews and edits strategy.
13. AI generates creative concepts/copy.
14. User approves selected creatives.
15. Platform validates campaign configuration.
16. User explicitly launches campaign.
17. Platform records external IDs and execution results.
18. Analytics jobs collect performance.
19. Funnel engine calculates conversion stages.
20. Financial engine calculates revenue, spend, ROAS, CPA and profit.
21. AI generates recommendations from validated metrics.
22. User can approve/reject recommendations.
23. Approved actions pass through validation and execution.
24. Audit log records every material event.

## 6. Funnel Model

Canonical stages:
- impression
- click
- landing_page_view
- product_view
- add_to_cart
- checkout_started
- purchase

Financial outcomes follow the funnel and are produced by the financial engine, not counted as funnel stages: revenue → profit (refunds, cost and repeat purchase are financial/customer metrics). Stages are shown only where data availability permits; unavailable stages are reported as unavailable, never as zero (Decision D18).

The funnel engine identifies conversion rates, drop-offs, campaign performance, product performance, landing-page issues, advertising inefficiencies and profitability problems.

The system should support additional stages later without breaking the canonical model.

## 7. Financial Model

The backend must calculate:
- Revenue
- Gross revenue
- Discounts
- Refunds
- Net revenue
- Advertising spend
- Product cost
- Shipping cost when available
- Transaction/payment fees when available
- Gross profit
- Contribution profit
- Margins
- ROAS
- CPA
- CAC where meaningful
- Budget utilization

Definitions must be centralized. Do not allow different screens to implement their own formulas.

## 8. AI Product Philosophy

AI should:
- understand business context,
- analyze normalized data,
- generate strategies,
- identify anomalies,
- propose experiments,
- explain recommendations,
- generate creative concepts,
- prioritize opportunities.

AI must not:
- invent metrics,
- fabricate platform capabilities,
- bypass permissions,
- directly execute unrestricted API calls,
- determine authoritative financial figures,
- override budget limits,
- silently publish campaigns.

## 9. Recommendation Lifecycle

Data
→ deterministic analytics
→ AI context (normalized AdVegaX data only)
→ LLM recommendation
→ structured schema validation
→ business-rule validation
→ policy validation
→ budget validation
→ risk validation
→ authorization
→ Action Engine
→ platform connector
→ execution
→ verification
→ audit log.

## 10. Operating Modes

### Manual
AI may analyze and recommend. User performs actions.

### Assisted
AI prepares actions. User explicitly approves each action.

### Autopilot
Only approved action classes may execute automatically within hard limits.

Example controls:
- maximum daily spend
- maximum budget increase
- maximum budget decrease
- minimum campaign age
- minimum conversion threshold
- maximum actions per day
- cooldown between similar changes

## 11. Multi-Tenancy

Every organization is an isolated tenant boundary.

Core entities must include organization ownership where applicable.

Authorization must verify:
- authenticated user,
- organization membership,
- role,
- resource ownership,
- action permission.

Never trust organization IDs supplied by clients without server-side authorization.

## 12. Roles

Initial roles:
- Owner
- Admin
- Manager
- Analyst
- Viewer

Example permissions:
- Owner: full organization access and billing
- Admin: operational administration
- Manager: campaigns/integrations/analytics
- Analyst: analytics and recommendations
- Viewer: read-only access

Permission checks must be centralized.

## 13. Auditability

Audit all:
- authentication/security events,
- integration changes,
- credential changes,
- campaign mutations,
- AI recommendations,
- approvals/rejections,
- budget changes,
- autopilot actions,
- billing events,
- important configuration changes.

Audit records should contain actor, organization, action, resource, timestamp, result, correlation/request ID, and relevant before/after information without exposing secrets.

## 14. Data Sources

### Commerce source
For each store, its connected commerce platform (Shopify or WooCommerce in MVP) is the financial source of truth for orders, revenue, discounts and refunds.

### Advertising sources
Google Ads and Meta provide advertising delivery/spend/performance data.

### Analytics source
GA4 provides traffic and behavioral analytics.

### Internal source
AdVegaX stores normalized data and derived calculations.

Conflicting source values must not be silently merged. Store source, timestamp, external ID and synchronization metadata.

## 15. Commercial Requirements

The architecture must support:
- subscriptions,
- trials,
- plans,
- invoices,
- payment status,
- usage limits,
- feature entitlements,
- agency accounts,
- multiple client organizations,
- multiple stores/ad accounts,
- multiple currencies,
- time zones,
- internationalization,
- notifications.

## 16. MVP Non-Goals

Do not build initially:
- fake engagement,
- fake social accounts,
- browser automation to bypass platform controls,
- unrestricted autonomous spending,
- unsupported platform functionality,
- unnecessary microservices,
- premature complex ML infrastructure.

## 17. Quality Requirements

Before production:
- automated tests,
- database migration verification,
- tenant isolation tests,
- authorization tests,
- integration tests,
- idempotency tests,
- retry tests,
- AI schema validation tests,
- financial calculation tests,
- security review,
- load/performance checks,
- backup/restore verification,
- staging deployment.

## 18. Development Strategy

Use a modular monolith first. Separate domain modules cleanly so high-load services can later be extracted.

Backend domains (domain-first layout, approved A3; each domain is created in the phase that needs it — see ARCHITECTURE.md §3):
- identity (users, credentials, sessions) — Phase 1
- organizations (organizations, memberships, invitations, roles) — Phase 1
- audit — Phase 1
- notifications (transactional email first) — Phase 1
- integrations (connections, external resources, organization links) — Phase 1B
- commerce (stores, catalog, inventory, orders, refunds) — Phase 2
- advertising — Phases 3–4
- analytics — Phase 5
- finance, reporting — Phase 6
- funnel — Phase 7
- ai, strategy — Phase 8
- creatives — Phase 9
- actions — Phase 10A
- recommendations — Phase 11
- automation — Phase 12
- billing — Phase 13
- agency capabilities within organizations — Phase 14

Platform-specific code lives only in `providers/`, never in these domains (D19).

## 19. Success Criteria

A merchant should be able to connect the core systems, select a product, generate and approve a campaign strategy, launch through official APIs, observe funnel/performance data, understand profitability, and receive controlled AI recommendations from one application.

The platform must be trustworthy enough that a merchant can understand **why** an action is recommended and **what** will happen before it is executed.

## 20. Approved Product-Owner Decisions (2026-10-08)

These decisions are architectural constraints. They are not permission to begin implementation. They supersede any earlier assumption that AdVegaX is Shopify-first or Shopify App Store-first.

**D1 — Name.** The product is **AdVegaX**; the repository/project identifier is `advegax`. The previous working name must not be used anywhere.

**D2 — Product type.** AdVegaX is an independent, multi-tenant SaaS web application. It is not Shopify-first, does not depend on Shopify for authentication or core architecture, and is not distributed exclusively through the Shopify App Store. Primary journey: AdVegaX website → create AdVegaX account → create organization/business → connect commerce platform → connect advertising platforms → connect analytics platforms → unified business/funnel view → AI strategy, analytics and optimization.

**D3 — Product philosophy.** Optimize for profitable business growth across the full chain in §1, not clicks, impressions or ad-platform ROAS alone.

**D4 — Provider architecture.** All integrations implement internal provider interfaces (`CommerceProvider`, `AdvertisingProvider`, `AnalyticsProvider`, future categories). Core business logic operates only on normalized internal models and contains no provider-specific logic.

**D5 — Initial integrations.** Commerce: Shopify, WooCommerce. Advertising: Google Ads, Meta. Analytics: GA4 Data API. Do not implement other platforms in the MVP; the architecture must allow them later without rewriting the core.

**D6 — Shopify App Store.** Not App Store-first. A public Shopify App Store listing may later be an additional acquisition channel; if built, it connects to the existing AdVegaX platform and must not make AdVegaX Shopify-dependent. Shopify integration uses current official APIs/authentication, minimum scopes, no deprecated APIs, no browser automation; current documentation is verified before implementation.

**D7 — Independent authentication.** Users can create and use an AdVegaX account without any external platform account, and can sign in with no platform connected. AdVegaX authentication (user, organization, membership, roles) is separate from platform connections (Shopify, WooCommerce, Google Ads, Meta, GA4).

**D8 — Documentation.** Approved specifications live in `docs/`. Further documents (`ENGINEERING_RULES.md`, `SECURITY.md`, `AI_ARCHITECTURE.md`, `INTEGRATION_GUIDES.md`, `DEPLOYMENT.md`, `TESTING_STRATEGY.md`, `ADR/`) are added only when required.

**D9 — Hosting.** Provider and region not yet selected. Containerized and portable; no proprietary hosting dependency without a strong architectural reason. Must support Docker, PostgreSQL, Redis, FastAPI, Next.js, Celery workers, scheduled jobs, HTTPS, secret management, logging, monitoring, backups, disaster recovery, staging and production.

**D10 — Sessions.** Secure server-managed sessions: HttpOnly cookie, Secure in production, appropriate SameSite, CSRF protection, server-side validation, expiration, revocation, logout, secure password hashing, OAuth where appropriate, MFA-ready, authentication auditing, account recovery. No sensitive tokens in localStorage; third-party OAuth credentials stay server-side.

**D11 — Multi-tenancy.** AdVegaX is multi-tenant; a tenant generally represents an organization/business: User → Membership → Organization → Stores / Accounts / Integrations / Data. A user may belong to multiple organizations in the future. Organizations are strictly isolated. Tenant identity is never trusted from arbitrary client input; authorization is always enforced server-side.

**D12 — PostgreSQL Row-Level Security.** RLS is an additional isolation layer: Authentication → Application Authorization → Tenant Context → ORM/Repository Controls → PostgreSQL RLS → Database. RLS does not replace application authorization; the application still enforces user roles, organization membership, permissions, resource-level authorization and platform-account permissions. The architecture must explicitly address connection pooling, transaction-scoped tenant context, background workers, Celery tasks, scheduled jobs, migrations, administrative operations, system-level operations, RLS bypass risks and testing. The test suite must contain explicit cross-tenant isolation tests.

**D13 — Domain layout.** `https://app.<primary-domain>` (web app), `https://api.<primary-domain>` (API); future `www.`, `docs.`, `status.`. Domain supplied later; never hard-coded. Environment-specific configuration for local development, staging and production. OAuth callback URLs are environment-specific. CORS uses explicit production allowlists.

**D14 — Platform accounts.** No credentials are assumed to exist. Shopify, WooCommerce, Google Ads, Meta and GA4 credentials/access are configured when each integration is implemented. Stripe is for the commercial billing phase and is not required for the foundation.

**D15 — Platform credential rules.** Never commit credentials, place them in source code, expose them to the frontend, or expose platform access tokens to the LLM. Use environment variables for development, managed secret storage for production, encrypted storage for persistent OAuth tokens, and separate credentials for development, staging and production. Use mocked providers or sandbox/test accounts where possible.

**D16 — AI architecture.** The AI layer is platform-independent and reasons over normalized AdVegaX data. It never directly executes external actions. Pipeline: Data → Deterministic Analytics → AI Context → LLM Recommendation → Schema Validation → Business Rules → Policy Validation → Budget Validation → Risk Validation → Authorization → Action Engine → Provider → Execution → Verification → Audit Log. The AI never has unrestricted access to databases, arbitrary APIs, advertising accounts, financial systems, billing, shell commands or arbitrary code execution.

**D17 — Financial intelligence.** AdVegaX independently and deterministically calculates revenue, refunds, discounts, advertising spend, CPA, ROAS, product cost, gross profit, contribution profit, margins, customer acquisition cost and budget utilization. The LLM may explain and recommend; it is never the financial source of truth.

**D18 — Funnel intelligence.** Unified funnel Impression → Click → Landing Page → Product View → Add to Cart → Checkout → Purchase → Revenue → Profit, where data availability permits; identifies conversion rates, drop-offs, campaign, product and landing-page issues, advertising inefficiencies and profitability problems.

**D19 — Platform independence (critical).** The AI, financial, funnel, optimization, recommendation, audit, billing, organization management, user management, RBAC, reporting and notification engines and the core product model belong to AdVegaX and must not be Shopify-specific (or specific to any platform). Platform-specific functionality stays inside integration/provider modules.

**D20 — Implementation sequence.** 1 Foundation · 2 Commerce (Shopify, WooCommerce) · 3 Google Ads · 4 Meta Ads · 5 GA4 · 6 Unified Analytics · 7 Funnel Intelligence · 8 AI Campaign Planner · 9 Creative Engine · 10 Campaign Builder · 11 Optimization Engine · 12 Controlled Autopilot · 13 Stripe Billing · 14 Agency Mode. Changes require a strong technical reason with dependencies explained.

**D21 — Development philosophy.** Built as a commercial production SaaS, not a prototype. Priorities: security, tenant isolation, maintainability, observability, testing, deterministic financial calculations, API correctness, idempotency, auditability, scalability, extensibility, documentation. Modular monolith; extract services only on demonstrated need.

**D22 — Core decision.** AdVegaX is an independent SaaS platform and the central intelligence and orchestration layer connecting multiple commerce, advertising and analytics platforms. Shopify is an integration, not the foundation. A merchant must be able to use AdVegaX without Shopify.

## 21. Phase 0 Approval Record (2026-10-08)

The product owner approved Architecture/Discovery Report v3 and the following. These are binding alongside D1–D22. The product owner remains the final authority for scope and architecture.

**A1 — Repository and file operations.** The repository `advegax` is controlled by the product owner. AI coding agents may create, modify, rename and move files, run Git operations, and delete files only when necessary for the approved architecture. Deletion is conservative: check references first; never delete specifications, architectural decisions, security/audit documentation, migration history, tests, configuration or important documentation merely because they appear unused; explain why deletion is necessary; list deleted files in the implementation report. Destructive or hard-to-reverse changes not clearly required by the approved architecture need approval first.

**A2 — Report v3 approved.** Mandatory principles: independent multi-tenant SaaS, not Shopify-first; Shopify is one commerce provider among several; WooCommerce, Google Ads, Meta and GA4 are first-version integrations per the roadmap; core logic platform-independent; provider capabilities explicitly represented; unavailable data never converted to zero; attribution never blindly dependent on one platform; multiple stores, ad accounts, currencies and time zones per business; tenant isolation at application, authorization, repository/query and RLS levels; AI is a reasoning/recommendation layer only; deterministic backend calculations are the source of truth; the Action Engine is mandatory before any campaign/account change; the phase order stands.

**A3 — Domain-first backend (C3).** Approved. Domain-oriented modules, not generic services/utilities. Phase 1 establishes the foundation without implementing future domains early.

**A4 — Phase 1 schema (C4).** Approved for the Phase 1 portion only. No speculative tables; future tables are introduced with the functionality that needs them unless foundational. The design must stay extensible for organizations, users, memberships, authentication/sessions, external connections, external resources, idempotency, webhook/event processing, auditability and synchronization state. Every table has a clear purpose, tenant relationship where applicable, constraints, indexes and documented relationships.

**A5 — Deterministic metrics (C5).** Approved. Derived metrics (ROAS, CPA, CTR, CPC, conversion rate, margin %, budget utilization, profit margin) are never primary sources of truth. Store underlying measurable values; calculate derived values deterministically. Cached or materialized derived values must be reproducible from source data. Financial calculations are testable independently of AI.

**A6 — Connection vs resource model (C7).** Approved. A **connection** is the authorization a user grants AdVegaX on an external platform; one connection can expose many **external resources** (stores, ad accounts, properties, business assets). Model: User → External Connection → External Resources → Organization Resource Links. Discovery and explicit linking are distinct: authorization never implies every accessible resource is linked. The model supports future reassignment/relinking without compromising tenant isolation or auditability. The exact schema is finalized in Phase 1 planning and documented before implementation.

**A7 — Authorization scope (C8).** MVP authorization is organization-level: User → Membership → Organization → organization-level role. No end-user resource-level permissions or related UI in Phase 1. The model separates (1) organization membership, (2) organization role, (3) resource ownership/linking, (4) future resource-level authorization, so per-store/per-ad-account permissions can be added later without redesign. In MVP, the "platform-account permissions" required by D12 are enforced as organization role + the platform resource being actively linked to the organization (layer 3).

**A8 — First-version authentication.** Email + password is the primary login method, with email verification, secure password hashing and server-managed sessions (Secure HttpOnly cookies, SameSite, CSRF protection, expiration, revocation, logout). The design must allow later Google OAuth, Microsoft OAuth, enterprise identity providers, MFA and passkeys without fundamental redesign. Authentication and authorization remain separate. Social login is not built until it is in an approved scope.

**A9 — Transactional email.** A Phase 1 dependency, supporting at minimum email verification, password reset and security/account notifications. Provider is configurable and not coupled to the authentication domain; no vendor hard-coded in business logic.

**A10 — Data availability.** Every integration states what it can and cannot provide. Availability states **available, unavailable, unsupported, not synchronized** are preserved end-to-end and never converted to 0 — especially for spend, revenue, conversions, attribution, product, campaign and financial metrics. Normalized data keeps source/provider and availability information where needed.

**A11 — Outbound network security (SSRF).** Store endpoints and other externally supplied URLs (notably WooCommerce) must not be usable to reach internal infrastructure. Protections cover allowed protocols, hostname validation, DNS resolution risks, private/internal IP ranges, redirects and re-validation after redirects, timeouts, response-size limits, safe outbound networking and credential protection — not URL-format validation alone. Documented and tested as part of the connector/security foundation.

**A12 — AI data boundary.** External Platforms → Provider Connectors → Normalized Data → Deterministic Calculations → Validated Business Context → AI Reasoning → Recommendation → Schema, Business Rule, Policy, Budget and Risk Validation → Authorization → Action Engine → Provider Connector → Execution → Verification → Audit Log. The AI never receives unrestricted access to PostgreSQL, ad platform APIs, billing systems, arbitrary HTTP requests, source code, production infrastructure or shell/code execution. Mandatory.

**A13 — Phase order.** Unchanged and approved: Phase 2 Shopify then WooCommerce; Phase 10 Action Engine then Campaign Builder. The Campaign Builder uses the Action Engine; there is no independent execution pathway.

**A14 — Shopify App Store.** A future distribution/acquisition channel only, not an MVP architectural dependency (consistent with D6, D22).

**Future-phase decisions.** Q5–Q16 (DISCOVERY_REPORT §14) are decisions for the phases that need them, not Phase 0 blockers.

**A15 — Phase 1A approval (2026-10-08).** The Phase 1A implementation plan (`docs/phases/PHASE_01A_PLAN.md`) and all its §22 defaults are approved: Python 3.12, PostgreSQL 16, Redis 7, `uv` with a committed lockfile, sessions 24 h idle / 14 days absolute, verification 24 h, password reset 30 min, invitation 7 days, §9 throttling defaults, unverified accounts may sign in but cannot create organizations or accept invitations, audit-log access for Owners and Admins, coverage ≥ 85 % overall and ≥ 95 % security-critical, `docs/SECURITY.md`, real-PostgreSQL testing, mandatory RLS and tenant-isolation testing, 1A → 1B → 1C sequence. Session and token lifetimes are centralized, configurable security settings (`SESSION_IDLE_TIMEOUT`, `SESSION_ABSOLUTE_TIMEOUT`, `EMAIL_VERIFICATION_TTL`, `PASSWORD_RESET_TTL`, `INVITATION_TTL`), never scattered constants. Implementation is authorized for Phase 1A only; Phase 1B and 1C each need separate approval.
