# Phase 1 — Foundation

**Status:** 1A and 1B implemented (awaiting review); 1C approved and in progress (1C-01 done) · **Depends on:** Phase 0 (complete) · **Milestone:** M1

## Goal
A secure, multi-tenant platform skeleton on which every later phase builds. A user can sign up with email + password, verify their email, sign in with no platform connected, create an organization, invite members and see an empty Connections page. No external platform integrations.

## Sub-phases
Each sub-phase has its own detailed plan, approved before code is written.

| Sub-phase | Scope | Plan |
|---|---|---|
| **1A — Platform core & identity** | Repository/tooling, backend core, PostgreSQL + RLS, identity (email + password, verification, sessions, CSRF), transactional email (outbox + worker), organizations, memberships, invitations, organization-level RBAC, audit log, security events, CI | `PHASE_01A_PLAN.md` (approved) · `PHASE_01A_REPORT.md` (implemented) |
| **1B — Integration foundation** | Connection → resource → organization-link model (A6), encrypted credential storage (envelope encryption interface), job framework (`job_runs`, retries, dead-letter, scheduler lock), provider interfaces, capability + availability model (A10), provider registry, fake provider, **SSRF-safe outbound HTTP client** (A11), rate-limiter primitive | `PHASE_01B_PLAN.md` (approved, A16) · `PHASE_01B_REPORT.md` (implemented) |
| **1C — Frontend shell** | Next.js + TypeScript strict; sign-up/verify/sign-in/reset pages, organization create/switch, members & invitations, empty Connections page; typed API client; CSRF handling; accessibility | `PHASE_01C_PLAN.md` (approved, A17) · `PHASE_01C_PROGRESS.md` (task reports) |

Why this split: 1A contains everything later work depends on for security (identity, tenancy, RLS, audit). 1B adds the platform-integration foundation without any real provider. 1C puts a UI on top of stable APIs.

## Out of scope for Phase 1
Real provider connectors, webhooks, product/order/ad data, finance, AI, billing, resource-level permissions, social/enterprise login, MFA (designed for, not built).

## Exit criteria (whole phase)
All sub-phase acceptance criteria met; cross-tenant suite covers every tenant table and route; security review of auth, sessions, CSRF, RLS and SSRF completed; `PROJECT_STATUS.md` updated.
