# Phase 14 — Implementation Report (Agency Mode)

**Status:** Implemented — awaiting your review. No Step 0: nothing external is involved.
**Plan:** `PHASE_14_PLAN.md`, approved 2026-10-28 (A33, all recommendations).
**Progress log:** `PHASE_14_PROGRESS.md`.

## 1. Summary

An agency can now manage its clients inside AdVegaX. It stays **off** (`AGENCY_ENABLED=false`) until you switch it on.

1. The agency, which is an ordinary organization, gets an **agency code** in Settings → Agency access.
2. A client's **owner** enters that code and chooses the agency's role: **Manager**, **Analyst** or **Viewer**.
3. The agency's owner or admin **accepts**.
4. The agency's people then open the client organization. Each person's role there is the **lower** of their own agency role and the role the client chose.
5. A banner says they are working "through" the agency.
6. Their actions appear in the **client's audit log**, marked with the agency.
7. Either side ends the access **at once**.

What an agency can never do:

- see or change the client's members, invitations or billing;
- change the client's organization settings;
- switch autopilot on;
- give another agency access.

The agency's **Clients** page shows each client on its own row, in that client's own currency:

- plan status;
- the last 30 days' ad spend and net sales;
- open recommendations;
- connections that need attention.

There are **no totals across clients**.

## 2. Delivered

| Task | Delivered |
|---|---|
| 14-01 | Migration 0025: `agency_grants`; `organizations.agency_code` |
| 14-02 | Access through an active grant in the server's tenant check (effective role, checked on every request) |
| 14-03 | Grants API (§19O); audit in both organizations and "via agency" on every delegated action; three owner emails |
| 14-04 | Clients list, each client computed separately |
| 14-05 | Settings → Agency access; Clients page and menu link; "through the agency" banner; client organizations in the organization switcher |
| 14-06 | API, unit, page and browser tests |
| 14-07 | This report |

## 3. Acceptance (plan §1, §4)

| Criterion | Result |
|---|---|
| Explicit grants from both sides, audited, revocable at once | ✅ |
| Delegated role never above either limit; never Owner or Admin | ✅ |
| Cross-client view without mixing data or currencies | ✅ |
| Isolation: agency ↔ client, client ↔ client, no grant, revoked grant, every route | ✅ |

## 4. Security controls

- **Same tenant rules as before.** Everything an agency person reads or changes runs in the client's own tenant context with forced RLS. There is no new cross-tenant query.
- **Grant table.** Readable only by the two organizations, and by active members of the agency. Only the client can create a grant.
- **Agency code lookup.** The server finds an agency by its code through a narrow read of organization id, name, status and code — nothing else.
- **Server-side caps.** The permissions an agency can never use (§1) are refused on the server, whatever the role.
- **Route sweep.** The tenant sweep covers the new routes.

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ✅ 2,115 passed, coverage 95.38 % |
| Frontend `npm run check` | ✅ 586 passed (branch coverage 85.4 %) |
| Browser (Playwright + accessibility) | ✅ 21 passed (new: `agency.spec.ts`; the whole suite now runs with agency mode on) |

New test files:

- `tests/api/test_agency_api.py`
- `tests/unit/test_agency_rules.py`
- `frontend/tests/features/agency.test.tsx`
- `frontend/e2e/agency.spec.ts`

## 6. Database

Migration **0025** (additive, reversible). See DATABASE_SCHEMA §14H.

## 7. New libraries

None.

## 8. Deviations from the plan

1. **The agency code** is created when an agency first asks for it ("Get an agency code"), not for every organization.
2. **A person in several agencies** with access to the same client gets the highest role any one of those agencies allows.
3. **"Via agency" in the audit log.** It is recorded for every action made through the web app and API. It is not recorded on the last step of connecting a platform: the platform's redirect back to AdVegaX arrives without the person's organization, so that one record is stored without the agency mark. Every later step is marked.
4. **The Clients link** appears in the agency's menu once at least one client has given it access.

## 9. Known limitations

- No agency pricing yet (Q-14-7). No per-client staff assignment. No white-labelling.
- Retention periods, launch languages and currencies (the rest of Q15) are still to decide before staging.

## 10. Your review checklist

**A. Decide or confirm:**

1. Roles an agency can get: Manager (default), Analyst or Viewer — never Owner or Admin.
2. That agency staff do not count towards the client's member limit, and that there is no agency price for now.
3. The deviations in §8.

**B. Try it in the app** (set `AGENCY_ENABLED=true` in the local settings file first):

1. In an agency organization: open **Settings → Agency access** and choose **Get an agency code**.
2. In a client organization, as its owner: enter the code, choose **Manager**, then **Give access**.
3. Back in the agency: **Accept**, then open **Clients**. Open the client and read the banner. Check that Members and Billing are refused.
4. In the client: open the **Audit log** and find the agency's actions. Then **End access**; the agency can no longer open the client.

**C. Set up:** nothing external is needed.

**D. Documents:**

- this report;
- API_SPECIFICATION §19O;
- DATABASE_SCHEMA §14H.

## 11. Next

1. **Your review** of Phases 12–14.
2. **Step 0** for Phases 8–13 once the keys are in place.
3. **Staging decisions** (Q15 remainder, Q16 hosting and email provider). Then the move to a staging server — every roadmap phase (1–14) is now built.
