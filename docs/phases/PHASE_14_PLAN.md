# Phase 14 — Agency Mode: Implementation Plan

**Status:** Draft — awaiting your approval · **Date:** 2026-10-28

> An agency (its own AdVegaX organization) manages several client organizations. A client **grants** the agency access; the agency's staff then work inside the client organization with a **limited role**, every action audited as "via <agency>", and either side can end it at once. Client data is never mixed: each client is read in its own tenant context, as today.

**Depends on:** Phases 1 (organizations, roles, audit), 13 (plans). **Governing:** DISCOVERY_REPORT §274 (grant model designed in Phase 1), A16 (connections stay per organization), Q15.

## 1. Objective

Agencies manage many clients safely: explicit, audited, revocable grants; delegated roles that can never exceed what the client allowed; a cross-client list that shows each client separately; isolation tests between agency and client and between clients.

## 2. Decisions needed from you

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-14-1** | Grant model | The agency is its **own organization**. Its owner shares an **agency code** (shown in its Settings). A **client owner** enters it under Settings → Agency access and picks the role; the agency's owner or admin **accepts**. | Client stays in control; both sides agree. |
| **Q-14-2** | Delegated role | Client chooses **Manager** (default), **Analyst** or **Viewer**. Never Owner or Admin: agency staff can never manage the client's members, billing, organization settings, or switch autopilot on. | Least privilege. |
| **Q-14-3** | Which agency staff | Every agency member gets **the lower of** their agency role and the granted role (an agency viewer stays a viewer). Per-client staff assignment later. | Simple first version; never above either limit. |
| **Q-14-4** | Ending access | Client owner or admin, or agency owner or admin, **revokes at once**; checked on every request. Revoked grants stay in the history. | Immediate and auditable. |
| **Q-14-5** | Cross-client view | A **Clients** page in the agency organization: one row per client — name, its plan status, last-30-day ad spend and net sales in **its own currency**, open recommendations, connections needing attention. **No totals across clients.** | Overview without mixing data or currencies. |
| **Q-14-6** | Audit | Every delegated action is recorded in the **client's** audit log with the person **and** "via <agency>"; the client sees it. The agency's log records grants accepted and ended. | Clients see what their agency did. |
| **Q-14-7** | Billing | **No agency pricing in this phase**: each client keeps its own plan; agency staff do **not** count towards the client's member limit; an agency may hold grants from any number of clients. Agency pricing later (with Q15). | Ship safely first; price from real use. |
| **Q-14-8** | Notifications | Client owners emailed when the agency accepts and when access ends; agency owners when a client grants or ends it. | No surprises. |
| **Q-14-9** | Rest of Q15 (retention, languages, currencies) | **Not in this phase** — decided before staging. | Separate concerns. |
| **Q-14-10** | Delivery | Tasks 14-01 … 14-07 (§7), **one report at the end** with your review checklist. | As every phase. |

## 3. Scope

- **Data — migration 0025:** `agency_grants` (client organization, agency organization, granted role, status `pending | active | revoked`, who granted, accepted and revoked, when). Readable by both organizations (forced RLS on either id); the agency code on `organizations` (random, regenerable).
- **Access path:** the tenant check (`resolve_tenant`) accepts a member of an agency with an **active** grant and gives the effective role (Q-14-3); all data is then read under the **client's** tenant context exactly as for its own members — no new cross-tenant query.
- **API:** grant, accept, revoke, list (both sides); agency code; `GET /organizations/{agency}/clients` (each client computed separately).
- **Web app:** Settings → Agency access (client); Clients page and code (agency); the organization switcher lists client organizations marked "via <agency>"; a banner inside a client organization when working via an agency.
- **Audit and emails** as Q-14-6, Q-14-8.

**Non-goals:** agency billing or white-labelling; per-client staff assignment; sharing one platform connection across organizations (A16 unchanged); combined reports across clients.

## 4. Security

- Grants need both sides; only the client's owner can create one; role capped (Q-14-2) on the server.
- Every request re-checks the grant; revocation is immediate.
- Isolation tests: agency ↔ client, client A ↔ client B through the same agency, an agency without a grant, a revoked grant, every organization route (the route sweep gains a "via agency" pass).
- Audit of every delegated action; agency members never see the client's billing, members or credentials.

## 5. Testing

API tests for the grant lifecycle, roles and caps, revocation, the Clients page figures; tenant isolation sweep via an agency; page tests; one browser test with accessibility checks (client grants, agency accepts, agency member opens the client, revokes).

## 6. Rollback

`AGENCY_ENABLED=false` (default until you switch it on): grants are ignored and the pages hidden. Migration 0025 is reversible.

## 7. Tasks

| Task | Content |
|---|---|
| 14-01 | Migration 0025; agency code; grant model |
| 14-02 | Access path in the tenant check; effective role; revocation |
| 14-03 | Grants API; audit "via agency"; emails |
| 14-04 | Clients overview API (each client separately) |
| 14-05 | Web app: Agency access, Clients page, switcher, banner |
| 14-06 | Isolation and lifecycle tests; browser test |
| 14-07 | `PHASE_14_REPORT.md` with your review checklist |

No Step 0 is needed (nothing external). No new library.

## 8. Approval checklist

Approve or change Q-14-1 … Q-14-10 and delivery 14-01 … 14-07, with one report at the end.
