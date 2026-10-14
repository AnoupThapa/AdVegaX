# AdVegaX — Project Status & Progress Log

**Last updated:** 2026-10-13
**Current phase:** Phase 2A approved (A18) and in progress · Phase 1 (1A, 1B, 1C) implemented — awaiting product-owner review
**Code written:** Phase 1A + 1B backend, Phase 1C web application · **Migrations:** 0001–0007 · **Integrations:** Shopify connector in progress (2A, simulator-tested; not yet tried on a live store) · test (fake) platform

Update this file at the end of every phase and every approved sub-phase (ROADMAP §5, step 13).

---

## 1. Phase tracker

| Phase | Name | Status | Notes |
|---|---|---|---|
| 0 | Architecture approval & bootstrap | ✅ **Complete** | Report v3 approved; A1–A14 recorded; specs consistent |
| 1A | Platform core & identity | ✅ **Implemented — awaiting review** | 141 tests, 98.5 % coverage; `phases/PHASE_01A_REPORT.md` |
| 1B | Integration foundation | ✅ **Implemented — awaiting review** | 277 tests, 98.4 % coverage; `phases/PHASE_01B_REPORT.md` |
| 1C | Frontend shell | ✅ **Implemented — awaiting review** | 251 unit + 9 end-to-end tests, axe 0 violations; `phases/PHASE_01C_REPORT.md` |
| 2A | Shopify (read-only) + finance core | ✅ **Implemented against the Shopify simulator — awaiting review**; live checks on a development store (2A-01) pending | 582 backend + 290 frontend + 10 end-to-end tests; `phases/PHASE_02A_REPORT.md` |
| 2B | WooCommerce (read-only) | **Approved (A19) — in progress** (Step 0 waits for WordPress downloads to be allowed) | `phases/PHASE_02B_PLAN.md`, `phases/PHASE_02B_PROGRESS.md` |
| 3 | Google Ads (read-only) | Not started | Start developer-token application early |
| 4 | Meta (read-only) | Not started | Start App Review / Business Verification early |
| 5 | GA4 (read-only) | Not started | Needs Q11 |
| 6 | Unified analytics & financial engine | Not started | Needs signed-off metric definitions (Q7) |
| 7 | Funnel intelligence | Not started | |
| 8 | AI campaign planner | Not started | Needs Q12 |
| 9 | Creative engine | Not started | |
| 10A | Action Engine | Not started | |
| 10B | Campaign builder | Not started | Uses Action Engine only (A13) |
| 11 | Optimization engine | Not started | |
| 12 | Controlled autopilot | Not started | Needs Q13 |
| 13 | Stripe billing & entitlements | Not started | Needs Q14 |
| 14 | Agency mode | Not started | Needs Q15 |

## 2. Completed work

| Date | Item | Output |
|---|---|---|
| 2026-10-08 | Read specifications; inspected repository (greenfield) | — |
| 2026-10-08 | Discovery report v1 (Shopify-first) | superseded |
| 2026-10-08 | Decisions D1–D22 received; specs moved to `docs/`, renamed, amended | `MASTER_SPECIFICATION.md §20` |
| 2026-10-08 | Shopify and WooCommerce facts verified against official docs | `DISCOVERY_REPORT.md §10` |
| 2026-10-08 | Architecture/discovery report v3 | `DISCOVERY_REPORT.md` |
| 2026-10-08 | Roadmap and per-phase plans | `ROADMAP.md`, `phases/` |
| 2026-10-08 | **Report v3 approved**; approval record A1–A14 | `MASTER_SPECIFICATION.md §21` |
| 2026-10-08 | Approved amendments applied (C3, C4, C5, C7, C8, auth, email, availability, SSRF, AI boundary) | all specs |
| 2026-10-08 | Final Phase 0 consistency review | `DISCOVERY_REPORT.md §16` |
| 2026-10-08 | Git repository initialised; documentation committed | local repo `advegax` |
| 2026-10-08 | Phase 1 split into 1A/1B/1C; Phase 1A plan written | `phases/PHASE_01_FOUNDATION.md`, `phases/PHASE_01A_PLAN.md` |
| 2026-10-08 | Phase 1A plan approved with configurable session/token settings (A15) | `MASTER_SPECIFICATION.md §21` |
| 2026-10-08 | Phase 1B plan drafted | `phases/PHASE_01B_PLAN.md` |
| 2026-10-08 | **Phase 1A implemented**: identity, sessions, CSRF, email outbox, organizations, invitations, RBAC, audit, RLS, CI | `backend/`, `phases/PHASE_01A_REPORT.md`, `SECURITY.md` |
| 2026-10-08 | Phase 1B plan approved (A16) | `MASTER_SPECIFICATION.md §21` |
| 2026-10-08 | Branches pushed to GitHub by the product owner | https://github.com/AnoupThapa/AdVegaX |
| 2026-10-08 | Phase 1C plan drafted; `AI_CONTEXT.md` added | `phases/PHASE_01C_PLAN.md`, `AI_CONTEXT.md` |
| 2026-10-08 | Phase 1C plan approved (A17) | `MASTER_SPECIFICATION.md §21` |
| 2026-10-08 | **1C-01** frontend scaffold, CSP/security headers, layout, tooling | `frontend/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-08 | Verification follow-up: route-guard tests, report corrections | `backend/tests/security/test_route_guards.py`, `phases/PHASE_01B_REPORT.md §13` |
| 2026-10-08 | **1C-02** generated API types, typed client (CSRF, retry, 401), error messages, query cache | `frontend/lib/api/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-08 | 1C-02 verification fixes (`HTTP_ERROR` message, full error-code scan, report corrections) | `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-08 | **1C-03** `GET /providers`; organization on platform-callback redirect | backend integrations, `API_SPECIFICATION.md §5` |
| 2026-10-08 | **1C-04** sign-up, verify email, sign-in/out, forgot/reset password pages; session handling; real-browser + axe check | `frontend/features/auth/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-08 | **1C-05** create/switch organization, settings, members (role, remove), invitations (send, revoke, accept); real-browser + axe check | `frontend/features/organizations/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-12 | Two Claude sessions had each built 1C-05; product owner kept the version on GitHub (`0b9d938`); the other version is kept only on a local backup branch. Decision: **one Claude session works on the repository at a time** | `phases/PHASE_01C_PROGRESS.md` (1C-05 independent verification) |
| 2026-10-12 | Independent two-person real-browser verification of 1C-05: all steps pass, axe 0 violations on 13 states, 0 CSP violations | `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-12 | Delivery estimate added | `ROADMAP.md §7` |
| 2026-10-12 | **1C-06** account security: sessions, sign out a device / everywhere, change password; fix: wrong password no longer ends the session; three-browser check | `frontend/features/account/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-12 | **1C-07** Connections pages: list, connect (https only), return notice, accounts found, link/unlink, sync status, history, rediscover, disconnect; real-browser + axe check | `frontend/features/connections/`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-12 | **1C-08** end-to-end + accessibility suite (Playwright + axe, 9 tests), CI `frontend`/`e2e` jobs, web Docker image; fixes: sign-out return address, out-of-date Overview text. **Phase 1C implemented** | `frontend/e2e/`, `phases/PHASE_01C_REPORT.md` |
| 2026-10-13 | **Phase 1C re-check** (independent review + full re-run): fixed stuck "Sync now" after an unreadable job, endless "Looking for accounts…", Docker route for the e2e suite, keyboard test strictness, CI now runs the standalone server; report corrections | `phases/PHASE_01C_REPORT.md §13`, `phases/PHASE_01C_PROGRESS.md` |
| 2026-10-13 | **Phase 2A plan drafted** (Shopify read-only + finance core): Shopify facts verified on 2026-10-13; recommendations for Q5–Q9; one store = one connection (Shopify allows one current token per app per store); App Store billing rule flagged for Q5 | `phases/PHASE_02A_PLAN.md` |
| 2026-10-13 | **Phase 2A plan v2** after independent review: 12 fixes (webhook CSRF exemption, pre-exchange one-store check, connect parameters, no stored webhook bodies, Shopify "sales reversals" definitions, reconnect reuse, streaming downloads, task order); live-testing environment blocked by network settings → decision §2A | `phases/PHASE_02A_PLAN.md §20` |
| 2026-10-13 | **A18 — Phase 2A approved** with all recommendations (Q5–Q9, D-2A-1…3) and option C: build now against documented formats + simulator; live Shopify checks later | `phases/PHASE_02A_PLAN.md` |
| 2026-10-13 | **2A-02** commerce data model (migration 0007): 11 tenant tables with RLS + composite keys, system-only webhook log (no bodies), one-live-connection-per-account rule; 16 isolation/integrity tests | `phases/PHASE_02A_PROGRESS.md`, `DATABASE_SCHEMA.md §4A` |
| 2026-10-13 | **2A-03** Shopify connect: store address or install link, HMAC + same-store checks, expiring tokens, one-store-one-organization enforced before the token exchange, reconnect reuse; Shopify simulator; 74 tests | `phases/PHASE_02A_PROGRESS.md`, `INTEGRATION_GUIDES.md` |
| 2026-10-13 | **2A-04** Token lifecycle: refresh before expiry under a per-account lock, rotated tokens saved, hourly keep-alive for idle refresh tokens, refused refresh → "Needs reconnecting", platform-revocation service for uninstalls; 14 tests | `phases/PHASE_02A_PROGRESS.md`, `SECURITY.md` |
| 2026-10-13 | **2A-05** Webhook intake: one signed endpoint per platform (CSRF exemption for that path only), HMAC on the raw body, replay window, de-duplication, metadata-only log with 30-day purge, uninstall → connection revoked, privacy requests recorded and audited; 57 tests | `phases/PHASE_02A_PROGRESS.md`, `API_SPECIFICATION.md §20`, `SECURITY.md` |
| 2026-10-13 | **2A-06** Initial store import: streaming download with per-provider host allowlist, Shopify bulk exports (catalogue, orders with sales agreements, refunds), normalized records, idempotent upserts with newer-wins guard, cost snapshot history, one-step-at-a-time import chain; migration 0008; 51 tests | `phases/PHASE_02A_PROGRESS.md`, `DATABASE_SCHEMA.md §4A`, `INTEGRATION_GUIDES.md` |
| 2026-10-13 | **2A-07** Keeping stores up to date: webhook → fetch current object (coalesced bursts, deletions, oversized → reconcile), hourly and nightly reconciliation through the import chain, cost valid at order time, cost-aware throttling back-off, privacy requests carried out (shop erasure); migration 0009; 33 tests | `phases/PHASE_02A_PROGRESS.md`, `INTEGRATION_GUIDES.md` |
| 2026-10-14 | **2A-08** Finance core v1: daily store figures from sales records (Shopify report dating, store time zone, exact decimals), COGS unknown when any cost is missing, coverage, derived figures with availability, display rounding; rebuilt after imports, reconciliations and webhooks; 26 golden + integration tests | `phases/PHASE_02A_PROGRESS.md`, `finance/definitions.py` |
| 2026-10-14 | **2A-09** Read API: stores (sync status, history limit), products (cursor, search, cost and stock availability), daily figures with availability and totals, "Sync now" (rate-limited, 409 when busy/unlinked); new store permissions; 19 tests | `phases/PHASE_02A_PROGRESS.md`, `API_SPECIFICATION.md §19A` |
| 2026-10-14 | **2A-10** Web app: Shopify connect form and install-link organization chooser, Stores tab with sync status, store page with revenue view (availability, never 0 for missing data) and "Sync now", products page with stock and cost availability; 39 tests + e2e step | `phases/PHASE_02A_PROGRESS.md` |
| 2026-10-14 | **2A-11** Whole-journey test against a strict-token Shopify simulator (connect → import → webhook → hourly check with token rotation → Sync now → uninstall → reinstall → store erasure, no token anywhere); browser test with an imported store + axe; fixed a test date time bomb (would have failed from December 2026); test code excluded from the Docker image. **Phase 2A implemented** (live checks pending) | `phases/PHASE_02A_REPORT.md`, `phases/PHASE_02A_PROGRESS.md` |
| 2026-10-14 | **Phase 2B plan drafted** (WooCommerce read-only): facts verified against WooCommerce docs on 2026-10-14; read-only keys cannot create webhooks → 15-minute checks; native COGS (10.3+) records order-time cost; SSRF hardening for merchant addresses; paged-import framework; parity tests with Shopify | `phases/PHASE_02B_PLAN.md` |
| 2026-10-14 | **A19 — Phase 2B approved** ("go ahead") with all recommendations. WordPress downloads still blocked, so Step 0 (2B-01) waits; building against documentation + simulator meanwhile | `phases/PHASE_02B_PLAN.md` |
| 2026-10-14 | **2B-02** Paged-import framework (one page per job step, resumable cursor, shared locks/upserts/figures) + migration 0010 (self-hosted store fields, excluded orders, page cursor); paged import proven identical to the bulk import; 10 tests | `phases/PHASE_02B_PROGRESS.md`, `DATABASE_SCHEMA.md §4A` |
| 2026-10-08 | **Phase 1B implemented**: connections/resources/links, encrypted credentials, SSRF-safe client, rate limiter, provider framework + fake platform, jobs with retry/dead-letter, single scheduler, audited denials | `backend/`, `phases/PHASE_01B_REPORT.md`, `SECURITY.md`, `INTEGRATION_GUIDES.md` |

## 3. Decision log

| ID | Decision | Status |
|---|---|---|
| D1–D22 | Product-owner decision set (name, platform independence, providers, integrations, auth, tenancy, RLS, domains, credentials, AI, finance, funnel, sequence, philosophy) | Approved — `MASTER_SPECIFICATION.md §20` |
| A1 | Repository control and conservative file-deletion rules | Approved |
| A2 | Report v3 and mandatory principles | Approved |
| A3 / C3 | Domain-first backend | Approved |
| A4 / C4 | Phase 1 schema only; tables introduced with their functionality | Approved |
| A5 / C5 | Derived metrics calculated, never primary truth | Approved |
| A6 / C7 | Connection → resources → organization links | Approved — implemented in 1B |
| A7 / C8 | Organization-level MVP authorization; resource-level later | Approved |
| A8 | Email + password with verification; future IdPs/MFA/passkeys without redesign | Approved |
| A9 | Transactional email in Phase 1, vendor-configurable | Approved |
| A10 | Availability states; never 0 for missing data | Approved |
| A11 | SSRF protections in connector/security foundation | Approved — implemented in 1B |
| A12 | AI data boundary | Approved |
| A13 | Phase order incl. 2A→2B and 10A→10B | Approved |
| A14 | Shopify App Store = future channel only | Approved |
| A15 | Phase 1A plan and §22 defaults; configurable security settings | Approved |
| A16 | Phase 1B plan and §20 defaults; organization owns connections, user authorizes; credentials never exposed; SSRF mandatory | Approved — implemented |
| A17 | Phase 1C plan with all §15 recommendations; task-by-task delivery | Approved — implemented, awaiting review |
| A19 | Phase 2B plan with all §2 recommendations (Q10a, Q10b, Q-2B-1…7); test environment A recommended, C-style until WordPress downloads are allowed | Approved 2026-10-14 ("go ahead") — in progress |
| A18 | Phase 2A plan v2 with all §2 recommendations (Q5–Q9, D-2A-1…3); live-testing option C | Approved 2026-10-13 — implemented, awaiting review (live checks pending) |

## 4. Open items

**Awaiting product owner now**
- Start the external approvals that take weeks (see `ROADMAP.md §7`): Google Ads developer token, Meta developer app + Business Verification, Shopify Partner account with a development store.
- Review of Phase 1: `phases/PHASE_01A_REPORT.md`, `phases/PHASE_01B_REPORT.md` (incl. deviations §10), `phases/PHASE_01C_REPORT.md` (incl. review follow-up §13).
- Review of Phase 2A: `phases/PHASE_02A_REPORT.md` (deviations §8, not verified §9, risks §10).
- When convenient: allow Shopify domains in Claude network settings (or decide a staging server) so the live Shopify checks can run; create a Shopify Partner account + development store (instructions on request).
- Run CI on GitHub: CI runs on pull requests and on pushes to `main` only — a push to `feature/phase-1a` does not start it. Open a pull request `feature/phase-1a → main` to run every job (backend, frontend, end-to-end, Docker, gitleaks).

**Future-phase decisions (not blockers until their phase)** — details in `DISCOVERY_REPORT.md §14`:
Q5 Shopify public-app approach (2A production) · Q6 same store/account in two organizations (2A) · Q7 financial metric definitions (2A/6) · Q8 customer PII policy (2A) · Q9 backfill depth/refresh (2A–5) · Q10 WooCommerce versions/HTTPS (2B) · Q11 GA4 aggregated model + Admin API (5) · Q12 LLM provider and creative scope (8/9) · Q13 autopilot action classes (12) · Q14 plans/pricing (13) · Q15 agency model, retention, launch markets (14/staging) · Q16 hosting provider/region and email provider (before staging).

**Informational:** C9 billing-provider interface (no Shopify billing in MVP); C10 Shopify public-app review applies to the Shopify connector in production (Q5).

## 5. Next actions

1. Product owner reviews Phase 1 (`PHASE_01A_REPORT.md`, `PHASE_01B_REPORT.md`, `PHASE_01C_REPORT.md`) and Phase 2A (`PHASE_02A_REPORT.md`).
2. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job (CI does not run on pushes to the feature branch alone).
3. Live Shopify checks (2A-01): Shopify Partner account + development store + app in the Dev Dashboard, and a reachable public HTTPS address (Shopify domains allowed in Claude network settings plus a tunnel, or a staging server).
4. Start the other external approvals: Google Ads developer token, Meta app review; ask Shopify Partner Support in writing about billing for the production distribution (Q5).
5. Privacy policy and merchant data-protection agreement before any other merchant connects.
6. Phase 2B (WooCommerce): review the plan `phases/PHASE_02B_PLAN.md` and decide Q10a, Q10b, Q-2B-1…7 and the test environment (§2A). Implementation starts only after approval.
