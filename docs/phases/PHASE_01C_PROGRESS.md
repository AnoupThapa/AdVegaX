# Phase 1C — Task Reports

Plan: `PHASE_01C_PLAN.md` (approved, A17). One report per task; the final `PHASE_01C_REPORT.md` follows task 1C-08.

| Task | Status |
|---|---|
| 1C-01 Scaffold, tooling, security headers + CSP, layout, design tokens | ✅ Done — awaiting review |
| 1C-02 API types + client | ✅ Done — awaiting review |
| 1C-03 Backend: `GET /providers`, `organization_id` on callback redirect | ✅ Done — awaiting review |
| 1C-04 Auth pages | ✅ Done — awaiting review |
| 1C-05 Organizations, members, invitations | ✅ Done — awaiting review |
| 1C-06 Account security | Not started |
| 1C-07 Connections pages | Not started |
| 1C-08 End-to-end + accessibility suite, CI, Docker, docs, report | Not started |

---

## 1C-01 — Scaffold, tooling, security headers, layout (2026-10-08)

**Completed**
- `frontend/` Next.js 16.4.0 (App Router, standalone output), React 19.3.0, TypeScript 6.0.3 strict (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`), Node.js 24 LTS (`.nvmrc`, `engines`, `engine-strict`), npm with exact versions and a committed lockfile.
- Tooling: ESLint 10 (Next.js core-web-vitals + TypeScript rules, warnings fail), Prettier, Vitest 5 + Testing Library (jsdom), coverage gate 85 % on `lib/`, `features/`, `components/`, `proxy.ts`.
- Security: `proxy.ts` sets a per-request nonce **Content-Security-Policy** (scripts only with nonce + `strict-dynamic`; `connect-src` limited to the API origin; `frame-ancestors`/`object-src`/`base-uri` none); static headers (nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, Permissions-Policy, COOP); HSTS when the API is https. Public configuration validated at build/start: API URL must be an https origin (http only for localhost), no credentials, no path.
- Guard rails: lint rules and a source test forbid `localStorage`/`sessionStorage`/`indexedDB`, `document.cookie`, `dangerouslySetInnerHTML`, `eval`/`Function`; only `NEXT_PUBLIC_API_BASE_URL` may reach the browser.
- Layout: skip link, header (banner landmark), `<main id="main">`, not-found page (does not reveal whether a resource exists), design tokens (light + dark), visible focus ring, reduced-motion support, `noindex`.

**Files changed**
- New: `frontend/**` (31 files: config, `proxy.ts`, `app/`, `components/layout/`, `lib/config/`, `lib/security/`, `tests/`, lockfile).
- Modified: `Makefile` (`frontend-install`, `frontend-check`, `frontend-dev`), `README.md` (frontend setup), `.editorconfig` (2-space indent for frontend code), `docs/MASTER_SPECIFICATION.md` (A17), `docs/phases/PHASE_01C_PLAN.md` (approved), this file, `PROJECT_STATUS.md`, `AI_CONTEXT.md`.
- Deleted: none.

**Tests**
- 35 passed (5 files) · coverage 100 % statements/branches/functions/lines.
- ESLint (0 warnings), Prettier, `tsc --noEmit` strict, production build: pass.
- `npm audit --omit=dev`: 0 vulnerabilities. `npm ci` from the lockfile: pass.
- Real browser (Chromium, production build): all 10 scripts and both stylesheets carry the nonce; **0 CSP violations**; client-side navigation works; first Tab stop is the visible skip link and Enter moves focus to `<main>`; 404 page returns HTTP 404.
- Colour contrast (computed): lowest text contrast 5.06:1 (light) and 7.30:1 (dark); WCAG AA needs 4.5:1.
- Backend unchanged (no backend code touched).

**Security**
- No secrets, session or API calls in the Next.js server; the proxy only sets headers.
- CSP verified in a browser; `unsafe-inline`/`unsafe-eval` never used in production.

**Migration:** none.

**Deviations**
1. **ESLint 10.12** instead of 9: ESLint 9 is end-of-life ("no longer supported"). Next.js's lint plugins declare support up to ESLint 9, so npm prints peer warnings; every rule (React, hooks, accessibility, Next.js, TypeScript) was verified to run under ESLint 10.
2. **Dependency audit gate covers production dependencies** (`npm audit --omit=dev`, fail on high). The dev-only lint chain has 5 "high" advisories that all trace to one unpatched library (`braces` ≤ 3.0.3, denial of service through attacker-written glob patterns — not reachable when linting our own code; no fixed version exists; npm's suggested "fix" is a downgrade to Next.js 14 lint config). Re-check at every task.
3. `upgrade-insecure-requests` is added only when the API is on https, so a local production build can still call `http://localhost:8000`.
4. `.editorconfig` gained a 2-space rule for frontend code (backend stays 4-space).

**Blocked:** none.

**Next task:** 1C-02 — API types generation + drift check, typed API client (CSRF, 401, error mapping), query setup.

**Verification follow-up (2026-10-08)**
- The browser check above ran on the build just before `app/icon.svg` and the `vitest.config.mts` rename. Re-run on the **final** build: 10/10 scripts carry the nonce, **0 CSP violations**, client-side navigation works, the icon is served; the only failed request is the intentional `/missing-page` 404.
- Correction: during the first run I described three 404s as "the missing test page and a missing favicon". That was not verified. The final run shows no favicon request failing; the earlier 404s came from the test visiting the missing page (the third was not identified and does not recur).

---

## 1C-02 — API types and client (2026-10-08)

**Completed**
- **Generated API types.** The backend exports its OpenAPI schema (`uv run python -m app.api.openapi_export`) to `frontend/lib/api/openapi.json`; `npm run api:generate` turns it into `lib/api/schema.d.ts`. Every API call in the web app is type-checked against it.
- **Two drift checks.** Backend test fails if the committed schema differs from the live API; frontend test fails if the committed types differ from the schema.
- **API client** (`lib/api/client.ts`, openapi-fetch): browser → API directly with the session cookie; CSRF token kept **in memory only**, fetched once (shared between concurrent requests) and sent on POST/PUT/PATCH/DELETE; fresh tokens from sign-in/sign-out are picked up; on `CSRF_FAILED` the token is refreshed and the request retried **exactly once** (body resent); on 401 the token is cleared and the app is notified (the cache is cleared; the redirect to the sign-in page is added in 1C-04, when that page exists).
- **Errors** (`lib/api/errors.ts`): `ApiError` with status, code, field details and request ID; every backend error code has our own user-facing wording (a test scans the backend for all three ways codes are declared, so new codes cannot be missed); server text and non-JSON bodies are never shown; network failures become `NETWORK_ERROR`.
- **Query cache** (TanStack Query): reads retry at most twice and only for network/5xx errors; mutations never retry; the whole cache is cleared when the session ends.
- **Safe redirects** (`lib/navigation/safe-next.ts`): only same-site relative paths are accepted for "return to" links.

**Files changed**
- New (frontend, 15 files): `lib/api/{client,csrf,errors,index}.ts`, `lib/api/openapi.json`, `lib/api/schema.d.ts` (generated), `lib/navigation/safe-next.ts`, `lib/query/query-client.ts`, `app/providers.tsx`, 6 test files.
- Modified (frontend, 5 files): `app/layout.tsx` (providers), `package.json`/lockfile (`openapi-fetch` 0.17.0, `@tanstack/react-query` 5.104.1, `openapi-typescript` 7.13.0 dev; `api:generate` script), `.prettierignore`, `eslint.config.mjs` (skip generated file).
- New (backend): `app/api/openapi_export.py`, `tests/unit/test_openapi_export.py`. No API behaviour changed.
- Deleted: none.

**Tests**
- Frontend: 71 passed · coverage 98.7 % statements, 99.1 % branches, 100 % functions. ESLint (0 warnings), Prettier, strict `tsc`, production build, `npm audit --omit=dev` (0 vulnerabilities): pass.
- Backend: 279 passed (+2) · 98.41 % coverage · ruff + `mypy --strict` clean.
- **Against the real API** (local uvicorn + PostgreSQL + Redis), driven by a temporary Node script that imitates a browser (cookie jar + `Origin` header) — **not a real browser**, so browser cookie rules and CORS were not exercised here; that is covered by the browser tests in 1C-08. Flow: register → sign in → forced bad CSRF token → `403 CSRF_FAILED` → new token → retry `202` → sign out → next call `401 UNAUTHENTICATED`. Sequence matched the design exactly.

**Security**
- CSRF token never stored outside memory (lint + source rules still pass); no secrets in browser code; open redirects blocked.

**Migration:** none.

**Deviations**
1. `openapi-typescript` declares support only for TypeScript 5; an npm `overrides` entry lets it use the project's TypeScript 6.0. Verified: generated types are identical through the command line and the programmatic API, and compile under strict `tsc`.
2. Error responses are not described in the OpenAPI schema, so the error envelope type (`ApiErrorBody`) is written by hand from API_SPECIFICATION §2.
3. A frontend test reads backend source files to make sure every backend error code has a message (deliberate cross-check; it needs the full repository checked out).
4. One defensive line in `safe-next.ts` (a fallback that valid input cannot reach) is not covered by tests.

**Not yet done (planned):** the shared `formatMetric` helper from plan §4.8 is not in the 1C-01…1C-08 task list; it will be added with the Connections pages (1C-07).

**Blocked:** none.

**Next task:** 1C-03 — backend: `GET /providers` and `organization_id` on the platform-callback redirect.

**Verification follow-up (2026-10-08)** — corrections after the final re-check:
1. The error-code scan only found codes written as `code = "X"`; it missed `HTTP_ERROR` (the backend's catch-all for unusual HTTP failures), which had no message. Fixed: the scan now also reads `error_body("X")` and `("X", "...")` declarations, `HTTP_ERROR` has its own message, and the test asserts the previously missed codes are found.
2. "Against the real API" was clarified: browser-like script, not a real browser.
3. File counts added (15 new, 5 modified in `frontend/`; my chat summary had said 13 new).
4. The 401 → sign-in redirect is marked as pending until 1C-04.

---

## 1C-03 — Backend: providers list and organization on the callback redirect (2026-10-08)

**Completed**
- **`GET /api/v1/providers`** — any signed-in user; returns the platforms this environment can connect to with public metadata only: `code`, `display_name`, `category`, `auth_scheme`, `capabilities`, `test_only`. Locally: the fake test platform. Staging/production: an empty list until Phase 2A, so the web app can show "No platforms available yet" without hard-coding platform names.
- **`organization_id` on the platform-callback redirect** — added for `connected`, `cancelled` and provider errors, i.e. only after the single-use state is validated **and** the signed-in user is re-confirmed as a manager of that organization. Never added for `invalid_state`, `session_mismatch` (another user, or signed out) or `not_permitted` (role lost), so no one learns an organization they cannot manage.
- `display_name` added to the provider contract; `ProviderRegistry.all()`.
- OpenAPI schema and the web app's generated types regenerated (both drift tests pass).

**Files changed**
- Backend: `app/providers/base/{interfaces,registry}.py`, `app/providers/fake/provider.py`, `app/domains/integrations/{schemas,service,router}.py`; tests `tests/api/test_connections.py`, `tests/providers/test_base.py`.
- Frontend: `lib/api/openapi.json`, `lib/api/schema.d.ts` (regenerated).
- Docs: `API_SPECIFICATION.md §5`, this file, status files.
- No database changes. Deleted: none.

**Tests**
- Backend: 281 passed (+2 new; 3 existing callback tests extended — corrected from "4" in verification) · 98.42 % coverage · ruff + `mypy --strict` clean. The route-guard sweep picked up the new endpoint automatically (signed-out → 401; now 30 protected routes).
- Callback: organization present for connected / cancelled / provider error; absent for invalid state, other user, signed out, role lost; connected redirect contains only `status`, `organization_id`, `connection_id` — no tokens, codes or state.
- Providers: exact field set; unverified, organization-less users can read it; deployed registry returns an empty list.
- Frontend: 71 passed, build and audit (0 production vulnerabilities) pass.

**Security**
- Provider list exposes no configuration or secrets (exact-fields test).
- Organization IDs appear in a redirect only for a user already confirmed as that organization's manager.

**Migration:** none.

**Deviations**
1. Plan §6 said `GET /providers` is "authenticated"; implemented as **any signed-in user** (email verification and organization membership not required), because the list is public, non-tenant metadata. Tell me if it should require a verified email.
2. The response also includes `auth_scheme` and `test_only` (not listed in the plan) so the UI can label test-only platforms; both are non-sensitive.

**Blocked:** none.

**Next task:** 1C-04 — auth pages (sign up, verify email, resend, sign in/out, forgot/reset password), including the 401 → sign-in redirect.

**1C-03 verification follow-up (2026-10-08):** test count corrected (3 extended tests, not 4); `SECURITY.md §10` now documents the callback organization rule and the provider list.

---

## 1C-04 — Sign-up, sign-in and password pages (2026-10-08)

**Completed**
- **Pages:** `/sign-up`, `/check-email`, `/verify-email`, `/sign-in`, `/forgot-password`, `/reset-password`; sign-out from the header; signed-in/signed-out area on the home page.
- **Session state:** `GET /auth/me` cached as the session (`null` = signed out). Sign-in, sign-out and password reset replace the cached session and drop every other cached response, so one user's data never shows for the next.
- **Session ends → sign-in:** `RequireAuth` (for the signed-in pages built from 1C-05) sends signed-out visitors to `/sign-in?next=<current page>` and back afterwards; a 401 while on such a page does the same (the 1C-02 pending item). `next` is validated (same-site paths only).
- **Email links:** the single-use token is read from the URL fragment, removed from the address bar immediately, and sent **once** (guarded against React running effects twice).
- **Feedback:** client checks for quick feedback (email shape, password 12–128 characters and not the email); the API stays authoritative and its password-policy messages appear on the right field (also when the API calls it `password` on the reset form). Other server text never shown. Errors are announced (`role="alert"`) with a support reference.
- **No account enumeration in the UI:** sign-up and forgot-password show the same result whether or not the address exists; sign-in failures share one message.
- **Unverified accounts:** can sign in; the home page explains they must verify before creating or joining an organization and offers to resend the link.
- **Accessibility:** labelled fields with linked hints/errors (`aria-describedby`, `aria-invalid`), focus moves to the page heading on arrival and to the first problem on a failed submit, 44 px touch targets, busy state on buttons.
- Shared UI: `Button`, `TextField`, `Alert`, `PageCard`.

**Files changed** (45)
- New (37): 6 page routes under `app/`, 5 files in `components/ui/`, 17 in `features/auth/`, 9 test files (`tests/features/` ×4, `tests/support/` ×4 helpers, `tests/unit/auth-logic.test.ts`).
- Modified (8): `app/page.tsx`, `app/providers.tsx` (401 → session ended), `components/layout/SiteHeader.tsx` (account links), `lib/api/client.ts` (fetch looked up per call), `lib/api/errors.ts` (`messageFor`), 3 existing tests updated for the new providers.
- Backend: none. Deleted: none.

**Tests**
- Frontend: 114 passed · coverage 98.6 % statements, 95.8 % branches, 100 % functions. ESLint (0 warnings), Prettier, strict `tsc`, production build, `npm audit --omit=dev` (0 vulnerabilities): pass.
- Component tests drive the real API client against a fake API (CSRF bootstrap, error envelope, 401 handling all exercised).
- **Real browser, real backend** (production build of the web app on :3000, uvicorn API on :8000, PostgreSQL, Redis, a local mail catcher; temporary script, not committed): sign up → wrong password refused → sign in (unverified notice) → open the emailed verification link → verified, token gone from the URL → sign out (API confirms 401) → forgot password → open the emailed reset link → new password saved → same link refused when reused → sign in with the new password, a malicious `next=//evil.example` ignored.
  - **axe accessibility scan on all 9 page states: 0 violations** (WCAG 2.0/2.1/2.2 A + AA and best-practice rules).
  - **0 Content-Security-Policy violations**, no page errors.
  - **No browser storage used** (localStorage, sessionStorage, readable cookies all empty).
  - Cookies set by the API: `HttpOnly`, `SameSite=Lax`. Cross-origin calls from `:3000` to `:8000` with credentials worked under the API's CORS allowlist (first real-browser proof of §4.1).
- Backend unchanged since the last full run (281 passed).

**Security**
- Tokens from email links never stay in the URL or history; CSRF token in memory only; no secrets in browser code; open redirects blocked; signed-in data cleared on sign-out, reset and session end.

**Migration:** none.

**Deviations**
1. Checking the session on public pages calls `GET /auth/me`; when signed out the API answers 401 and the browser console logs a "failed to load resource (401)" line. Harmless (it is how "signed out" is detected) but visible to anyone opening developer tools. A dedicated session-status endpoint returning 200 could remove it — a backend change I have not made.
2. Client-side password rules copy the API defaults (12–128). If the API's configured limits change, the API's own message still appears.
3. The home page gained a small signed-in/signed-out area (not listed in the plan's page list); organization pages arrive in 1C-05.
4. Component tests use Testing Library's built-in `fireEvent`; no new test dependency was added.

**Blocked:** none.

**Next task:** 1C-05 — organizations: create, switch, settings, members, invitations, accept invitation.

---

## 1C-05 — Organizations, members and invitations (2026-10-08)

**Completed**
- **Pages:** `/orgs/new` (create), `/orgs/[organizationId]` (overview, empty state for future reports), `/orgs/[organizationId]/members` (members + invitations), `/orgs/[organizationId]/settings`, `/invitations/accept`.
- **Create organization:** name, reporting currency (ISO 4217 list with names) and time zone (IANA list, defaults to the browser's). Unverified users see the verification notice instead of the form. The creator lands on the new organization; the session is refreshed so the switcher lists it.
- **Organization switcher** in the header (from `GET /auth/me` memberships): disclosure button with plain links; Escape (focus returns) and click-outside close it. Home page lists the user's organizations with roles and a create link.
- **Organization shell:** signed-in only (`RequireAuth`), loads `GET /organizations/{id}`, section navigation with `aria-current`. **404 from the API → the same "Page not found" as a missing page** (no hint whether the organization exists). Malformed IDs are never sent to the API.
- **Settings:** owners/admins edit name, currency, time zone; only changed fields are sent (`PATCH`). Other roles see a read-only summary.
- **Members:** list (name, email, role, status, joined). Owners/admins change roles (select + explicit "Save role", never on change) and remove members after a confirmation dialog (native modal `<dialog>`, focus starts on Cancel, Escape cancels). Role options mirror the API rules: only owners grant Owner, nobody assigns above their own role, admins cannot touch owners. Removing yourself is offered as "Leave" with its own warning and goes home afterwards; the API's last-owner rule (409 `LAST_OWNER`) is shown as a message.
- **Invitations** (owners/admins only; other roles never request the list): invite by email + role (role description shown as the hint; default Viewer), list with status (waiting / accepted / revoked / expired) and expiry, revoke pending ones. `ALREADY_MEMBER` and validation errors explained.
- **Accept invitation:** token read from the URL fragment and removed from the address bar at once (same helper as 1C-04). **Accepting needs an explicit click** (no automatic join on page load). Signed out → "Sign in to accept" with `next=/invitations/accept`; the token is kept **in memory only** during that same-tab detour (reload or new tab forgets it — the person reopens the email link). Unverified → verification notice. Email mismatch → explained, token kept, "Sign out and switch account". Used/expired/invalid → token dropped, "ask for a new invitation". Temporary failures keep the token so the person can retry. A second invitation link opened in the same tab (fragment-only change, no reload) is picked up and starts afresh.
- **Role-based visibility** (`features/organizations/permissions.ts`) mirrors API §24 for usability only; every action is still authorized by the API.
- Shared UI: `SelectField`, `ConfirmDialog`, `PageHeading` (focus to the heading on arrival); `Button` gained a `danger` variant and ref forwarding.

**Files changed** (39 in `frontend/`)
- New (30): 6 route files (`app/orgs/new`, `app/orgs/[organizationId]/{layout,page,members/page,settings/page}`, `app/invitations/accept/page`), 3 in `components/ui/`, 17 in `features/organizations/`, 4 test files (`tests/features/organizations.test.tsx`, `tests/features/members-and-invitations.test.tsx`, `tests/unit/organization-logic.test.ts`, `tests/support/organizations.ts`).
- Modified (9): `app/globals.css` (danger contrast token), `components/ui/{Button.tsx,ui.module.css}`, `components/layout/SiteHeader.module.css` (wraps on phones), `features/auth/{AccountNav.tsx,AccountNav.module.css,HomeSession.tsx}` (switcher, organization list, email hidden on phones), `features/auth/fragment-token.ts` (opt-in `followHashChanges`, default off — 1C-04 pages unchanged), `tests/support/navigation.ts` (`useParams`).
- Backend: none. Database: none. Deleted: none.

**Tests**
- Frontend: **184 passed** (+70) · coverage 98.7 % statements, 94.0 % branches, 100 % functions, 99.9 % lines (`features/organizations` 99.5 % statements). ESLint (0 warnings), Prettier, strict `tsc`, production build, `npm audit --omit=dev` (0 vulnerabilities): pass.
- Component tests drive the real API client against a fake API: role-based visibility for owner/admin/manager, role change + refusal (value restored), remove/leave with dialog (Cancel, Escape, confirm), last-owner refusal, invitation send/validation/`ALREADY_MEMBER`/revoke, accept flows (explicit click sends the token once in Strict Mode, sign-in detour, mismatch, final vs temporary errors, same-tab second link), 404 → not found, malformed ID → no API call, settings sends only changed fields.
- **Real browser, real backend** (production build on :3000, uvicorn API on :8000, PostgreSQL 16, Redis 7, Celery worker + beat, a local SMTP catcher; temporary Playwright script, not committed): **34/34 checks passed** — owner creates an organization, edits settings, switcher by keyboard, invites (link read from the real email), revokes, duplicate-member message; a new user opens the invitation signed out (token gone from the URL), signs up, verifies, signs in, reopens the link and accepts as Manager (read-only members and settings); a reused link is refused; an existing user goes through the sign-in detour and accepts (memory only); owner changes a role, removes a member via the dialog, is stopped from leaving as last owner; the removed member and a malformed ID get "Page not found"; an email-mismatch attempt does not consume the link (the right person accepts it afterwards); an unverified user sees the notice instead of the create form; a signed-out visitor to an organization page returns there after sign-in; no horizontal scroll at 375 px.
  - **axe on 15 page states: 0 violations** (WCAG 2.0/2.1/2.2 A + AA and best-practice rules), including mobile, the open switcher and the dialog.
  - **0 Content-Security-Policy violations**, no page errors; no localStorage/sessionStorage/readable cookies.
- Backend unchanged; 281 passed in this environment before the work started.

**Security**
- Invitation tokens never stay in the URL or history and are never written to browser storage; held in a module variable only while needed.
- Non-members cannot tell whether an organization exists (same not-found page; malformed IDs not sent).
- Role checks in the UI are cosmetic; API authorization unchanged.

**Migration:** none.

**Deviations**
1. **Explicit "Accept invitation" click** instead of accepting on page load (plan did not specify). Prevents joining by accident (e.g. a link preview or the wrong account).
2. **New invitees** must reopen the invitation link after signing up and verifying (verification usually opens a new tab, which cannot see the in-memory token). Persisting the token anywhere would contradict §7.
3. **Suspend/reactivate** members is supported by the API but not offered in the UI (plan lists change role and remove); suspended members are shown with their status.
4. Organization **slug** is not shown or editable; the API derives it from the name.
5. Currency and time-zone choices come from the browser's built-in lists; saved values stay selectable even if a browser lists them differently (e.g. `Asia/Katmandu` vs `Asia/Kathmandu`).
6. "Leave organization" is only possible for owners/admins, because the API requires `members.manage` to remove any membership, including one's own. Other roles cannot leave by themselves — a product decision for later.
7. On phones the header hides the signed-in email (switcher and sign-out stay); tables become stacked cards.
8. Found and fixed during browser testing: a second invitation link in the same tab was ignored; tables widened the page on phones; the table scroll area was not keyboard-focusable.

**Blocked:** none.

**Next task:** 1C-06 — account security: sessions (list, revoke one, sign out everywhere), change password.

### 1C-05 — independent verification (2026-10-12)

Two Claude sessions each built 1C-05 from the same starting point (1C-04). The product owner chose the version already on GitHub (`0b9d938`, above); the other session's version is not used (kept only on a local backup branch, never pushed). The other session then verified this version independently, without changing it:

- Lint, format, strict types, 184 tests (98.7 % statements), build, production audit (0 vulnerabilities): **pass**, matching the report above.
- **Real browser, real backend, two separate people, real emails:** A signs up and verifies → creates an organization → invites B as Manager → renames the organization. B (signed out) opens the invitation email → "Sign in to accept" → signs in → returned to the invitation → accepts → lands in the organization; as Manager sees no member controls and read-only settings. Organization menu opens and closes with Escape. A changes B to Viewer (explicit save) → removes B through the confirmation dialog → B leaves the members table (the accepted invitation stays in the invitation history, as intended) → B gets "Page not found". A signed-out visitor to a members page is sent to sign in with the right return address.
- **axe: 0 violations on 13 page states** (including the confirmation dialog and the open organization menu); **0 security-policy violations**; no browser storage.
- **Defects found: none.**
- Added one safety rule: inline `style` attributes are now rejected by the source-rules test (they are blocked by the security policy when a page first loads); the current code already complies.

