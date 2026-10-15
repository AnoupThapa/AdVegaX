# AdVegaX — Implementation Roadmap

**Version:** 1.2 · **Date:** 2026-10-08 · **Status:** Approved (Phase 0 approval, MASTER_SPECIFICATION §21 A13)

Follows the product-owner sequence (Decision D20). Two phases are split for technical reasons without changing the order: **Phase 2 Commerce = 2A Shopify → 2B WooCommerce**, and **Phase 10 = 10A Action Engine → 10B Campaign Builder** (see `DISCOVERY_REPORT.md §13`).
**Source:** `DISCOVERY_REPORT.md` §13–§14, `MASTER_SPECIFICATION.md` §20

This roadmap splits AdVegaX into phases. Each phase has its own plan in `docs/phases/`. A phase plan is a scope and checklist, **not permission to implement**: every phase starts with the per-phase workflow below and needs approval before code is written.

---

## 1. Roadmap principles

1. **Foundation before features.** Tenancy, RLS, auth, audit, encryption, idempotency and jobs exist before any integration.
2. **Read before write.** Every integration ships read-only first. External mutations arrive only with the Action Engine (Phase 10A).
3. **Deterministic before AI.** Finance and analytics are correct and tested before AI consumes them.
4. **Platform independence is proven early.** A second commerce provider (WooCommerce, Phase 2B) follows Shopify immediately.
5. **Human approval before autonomy.** Assisted mode is proven before autopilot.
6. **No invented API behaviour.** Each integration phase starts by verifying current official documentation.
7. **Every phase leaves the system releasable** (tests, lint, types, migrations, docs green).

---

## 2. Phase overview

| Phase | Name | Goal | Depends on | Status |
|---|---|---|---|---|
| 0 | Architecture approval & bootstrap decisions | Approved architecture (DISCOVERY_REPORT v3) | — | ✅ **Complete** |
| 1 | Foundation — 1A platform core & identity · 1B integration foundation · 1C frontend shell | Secure multi-tenant platform skeleton: identity, sessions, email, orgs, RBAC, RLS, audit, CI (1A); connections/resources, encryption, jobs, provider framework, SSRF client (1B); UI shell (1C) | 0 | **Implemented (1A, 1B, 1C) — awaiting review** |
| 2A | Commerce — Shopify (read-only) | Connect Shopify stores; import catalogue, inventory, orders, refunds; finance core | 1 | **Implemented against the simulator — awaiting review**; live checks pending |
| 2B | Commerce — WooCommerce (read-only) | Connect WooCommerce stores safely; same normalized models; proves abstraction | 2A | **Implemented against the WooCommerce simulator — awaiting review** (A19); live Step 0 pending |
| 3 | Advertising — Google Ads (read-only) | Accounts, structure, daily performance | 1 | Plan drafted — awaiting approval (`phases/PHASE_03_PLAN.md`) |
| 4 | Advertising — Meta (read-only) | Accounts, structure, insights | 1 | Not started |
| 5 | Analytics — GA4 (read-only) | Property discovery, aggregated behaviour data | 1 | Not started |
| 6 | Unified analytics & financial engine | One trustworthy cross-source view of revenue, spend, cost and profit | 2A, 3, 4, 5 (2B recommended) | Not started |
| 7 | Funnel intelligence | Source-labelled funnel stages and conversion rates | 6 | Not started |
| 8 | AI campaign planner | Schema-validated AI strategies grounded in deterministic data | 2A, 6 | Not started |
| 9 | Creative engine | AI copy concepts, versions, approval workflow, asset storage | 8 | Not started |
| 10A | Action Engine | The single, audited, idempotent gate for external mutations | 1, 3, 4 | Not started |
| 10B | Campaign builder | Approved strategy + creatives → validated, explicitly launched campaigns | 8, 9, 10A | Not started |
| 11 | Optimization engine | AI recommendations → approval → Action Engine | 6, 7, 8, 10A | Not started |
| 12 | Controlled autopilot | Whitelisted actions within hard limits, kill switch | 11 + proven 10A | Not started |
| 13 | Stripe billing & entitlements | Plans, subscriptions, usage limits | 1 (stub); parallel after 6 | Not started |
| 14 | Agency mode | Agencies managing many client organizations safely | 13 | Not started |
| — | Production-readiness gate | Security review, load test, backup/restore drill, staging soak | Before first paying customer | — |

---

## 3. Dependencies

```text
0 ─► 1 ─┬─► 2A Shopify ─► 2B WooCommerce ─┐
        ├─► 3 Google Ads (read) ──────────┤
        ├─► 4 Meta (read) ────────────────┼─► 6 Unified analytics + finance ─► 7 Funnel
        └─► 5 GA4 (read) ─────────────────┘            │
                       2A + 6 ─► 8 AI planner ─► 9 Creative
                       1 + 3 + 4 ─► 10A Action Engine
                       8 + 9 + 10A ─► 10B Campaign builder
                       6 + 7 + 8 + 10A ─► 11 Optimization ─► 12 Autopilot
1 (entitlement stub) ─► 13 Billing (can run in parallel after 6) ─► 14 Agency
External platform approvals gate production use of 2A, 3, 4, 5 and write access in 10A/10B.
```

Phases 3, 4 and 5 are independent of each other and of 2A/2B, and can run in any order after Phase 1. Only one AI agent edits the repository at a time (PROJECT_RULES §15), so "parallel" means "no ordering constraint", not concurrent edits.

---

## 4. Release milestones

| Milestone | After phases | What a user can do |
|---|---|---|
| M0 Architecture approved | 0 | — |
| M1 Platform foundation | 1 | Sign up, create an organization, invite members, see empty Connections page |
| M2 Connected data | 2A–6 | Connect store, ads, GA4; see unified revenue, spend, cost, profit (read-only) |
| M3 Insight | 7–9 | See the funnel; generate AI strategies and creative drafts (no execution) |
| M4 Controlled execution | 10A–11 | Launch approved campaigns; approve AI recommendations that execute safely |
| M5 Autopilot beta | 12 | Opt in to bounded automatic actions |
| M6 Commercial launch | 13 + readiness gate | Paid plans |
| M7 Agency | 14 | Agencies manage client organizations |

Whether to sell earlier (for example an insights-only plan after M2/M3) is a **commercial decision for the product owner**; it would move Phase 13 earlier.

---

## 5. Per-phase workflow (mandatory)

Every phase — and every milestone inside a phase — follows PROJECT_RULES §3:

1. Read relevant specifications · 2. Inspect existing implementation · 3. Explain intended changes · 4. Identify affected files · 5. Identify risks → **approval** → 6. Implement · 7. Run tests · 8. Run linting · 9. Run type checking · 10. Verify migrations · 11. Verify security boundaries · 12. Verify tenant isolation · 13. Update documentation (`PROJECT_STATUS.md` + specs) · 14. Report what changed · 15. Report remaining issues.

A phase is complete only when its exit criteria are met and `PROJECT_STATUS.md` is updated.

---

## 6. Phase plans

| File | Phase |
|---|---|
| `phases/PHASE_00_ARCHITECTURE_APPROVAL.md` | 0 |
| `phases/PHASE_01_FOUNDATION.md` | 1 (overview of 1A/1B/1C) |
| `phases/PHASE_01A_PLAN.md` | 1A detailed implementation plan |
| `phases/PHASE_01A_REPORT.md` | 1A implementation report |
| `phases/PHASE_01B_PLAN.md` | 1B detailed implementation plan (approved, A16) |
| `phases/PHASE_01B_REPORT.md` | 1B implementation report |
| `phases/PHASE_01C_PLAN.md` | 1C detailed implementation plan (approved, A17) |
| `phases/PHASE_01C_PROGRESS.md` | 1C task reports |
| `phases/PHASE_01C_REPORT.md` | 1C implementation report |
| `phases/PHASE_02A_PLAN.md` | 2A detailed implementation plan (approved, A18) |
| `phases/PHASE_02A_PROGRESS.md` | 2A task reports |
| `phases/PHASE_02A_REPORT.md` | 2A implementation report |
| `phases/PHASE_02B_PLAN.md` | 2B detailed implementation plan (approved, A19) |
| `phases/PHASE_02B_PROGRESS.md`, `phases/PHASE_02B_REPORT.md` | 2B task reports and phase report |
| `phases/PHASE_02A_SHOPIFY.md` | 2A |
| `phases/PHASE_02B_WOOCOMMERCE.md` | 2B |
| `phases/PHASE_03_GOOGLE_ADS.md` | 3 |
| `phases/PHASE_04_META_ADS.md` | 4 |
| `phases/PHASE_05_GA4.md` | 5 |
| `phases/PHASE_06_UNIFIED_ANALYTICS_FINANCE.md` | 6 |
| `phases/PHASE_07_FUNNEL.md` | 7 |
| `phases/PHASE_08_AI_PLANNER.md` | 8 |
| `phases/PHASE_09_CREATIVE_ENGINE.md` | 9 |
| `phases/PHASE_10A_ACTION_ENGINE.md` | 10A |
| `phases/PHASE_10B_CAMPAIGN_BUILDER.md` | 10B |
| `phases/PHASE_11_OPTIMIZATION.md` | 11 |
| `phases/PHASE_12_AUTOPILOT.md` | 12 |
| `phases/PHASE_13_BILLING.md` | 13 |
| `phases/PHASE_14_AGENCY.md` | 14 |

---

## 7. Delivery estimate (2026-10-12)

**Rough ranges, not commitments.** They assume one AI agent building task by task, each task reviewed and approved by the product owner before the next, and that open decisions (DISCOVERY_REPORT §14, Q5–Q16) are answered when their phase starts. Review turnaround and external approvals usually decide the calendar more than build effort.

| Phase | Build effort (calendar, with prompt reviews) | Outside dependencies (start early) |
|---|---|---|
| **M1 Platform foundation** | **Built — reached when you approve Phase 1** | — |
| 2A Shopify (read-only) + finance core | 3–4 weeks | Shopify Partner account + development store; Q5–Q9 |
| 2B WooCommerce (read-only) | 1–2 weeks | A test WordPress/WooCommerce site; Q10 |
| 3 Google Ads (read-only) | 2–3 weeks | **Developer token (Basic access) — Google review, days to weeks**; test account for development |
| 4 Meta (read-only) | 2–3 weeks | **Meta App Review + Business Verification — often 2–6 weeks** |
| 5 GA4 (read-only) | 1–2 weeks | Google Cloud project, OAuth consent screen; Q11 |
| 6 Unified analytics & finance | 3–4 weeks | Signed-off metric definitions (Q7) |
| **M2 Connected data (read-only)** | **~3–4 months from now** | |
| 7 Funnel | 1–2 weeks | |
| 8 AI planner · 9 Creative engine | 4–6 weeks | LLM provider and creative scope (Q12) |
| **M3 Insight** | **~5–6 months from now** | |
| 10A Action Engine · 10B Campaign builder | 5–7 weeks | Write-access scopes approved by Google and Meta |
| 11 Optimization · 12 Autopilot | 4–6 weeks | Autopilot action classes (Q13) |
| 13 Billing | 2–3 weeks | Stripe account; plans/pricing (Q14) |
| Production-readiness gate | 3–4 weeks | Hosting choice (Q16); independent security review / penetration test by a human firm |
| **M6 Commercial launch (full MVP)** | **~9–12 months from now** | |
| 14 Agency mode | 2–3 weeks | Q15 |

Ways to reach paying customers sooner: sell an insights-only plan after M2 or M3 (moves Phase 13 earlier — a commercial decision), and start the Google, Meta and Shopify approvals now so they run in parallel with the build.
