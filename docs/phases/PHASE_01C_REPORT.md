# Phase 1C — Implementation Report (Web application shell)

**Date:** 2026-10-12 · **Branch:** `feature/phase-1a` · **Status:** Implemented — awaiting product-owner review
**Plan:** `PHASE_01C_PLAN.md` (approved, A17) · Task-by-task reports: `PHASE_01C_PROGRESS.md` (1C-01 … 1C-08).
No real platform integration (Shopify, WooCommerce, Google Ads, Meta, GA4) was started.

---

## 1. Summary

AdVegaX now has a working web application on top of the Phase 1A/1B API. A person can:

sign up → verify their email → sign in (and reset a forgotten password) → create or switch organization → change its settings → invite people and manage their roles → accept an invitation → see and end their own sessions, change their password → open the Connections page: connect the local test platform, see the accounts it finds, link/unlink them, request a sync and watch it finish, view link history, check for new accounts, and disconnect.

Everything runs against the real API. The signed-in pages are client-rendered and call the API directly; the Next.js server holds no session and no secrets (plan §4.1). In staging/production the Connections page shows "No platforms are available to connect yet" until Phase 2A.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 1C-01 | Next.js 16.4 / React 19.3 / TypeScript 6.0 strict app; nonce CSP + security headers in `proxy.ts`; layout, skip link, design tokens; ESLint, Prettier, Vitest |
| 1C-02 | Generated API types with drift tests; typed API client (in-memory CSRF token with one retry, 401 handling, error-code → message mapping, request ID shown); TanStack Query setup |
| 1C-03 | Backend: `GET /providers`; `organization_id` on the platform-callback redirect (+ API and route-guard tests) |
| 1C-04 | Sign up, verify email, resend, sign in/out, forgot/reset password; session handling and redirect back after sign-in |
| 1C-05 | Create/switch organization, settings, members (change role, remove), invitations (send, revoke, accept) |
| 1C-06 | Account security: sessions (sign out a device / everywhere), change password; fix: a wrong password no longer ends the session |
| 1C-07 | Connections pages; `formatMetric` ("never show unavailable data as 0") |
| 1C-08 | End-to-end + accessibility suite, CI jobs, web Docker image, docs; two defects found and fixed (§7) |

Frontend size: 94 source files, 23 unit/component test files, 6 end-to-end spec files. Backend changes in Phase 1C: only 1C-03.

## 3. Acceptance criteria (plan §12)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | The journey works in a browser against the real API, locally and in CI | ✅ locally · CI job ready, not yet run on GitHub | `e2e/journey.spec.ts` passes (3 consecutive runs, one exactly as CI runs it). CI runs on a pull request (see §9) |
| 2 | No token, CSRF value or secret in browser storage, URLs (after load), logs or the Next.js server | ✅ | e2e: storage + readable cookies checked on every audited page; CSRF header value never stored; email tokens removed from the address; platform tokens never in the page; source-rules test + lint forbid storage/cookie access; no server-side secrets (only the public API address) |
| 3 | Every page passes axe with zero serious/critical violations and works with keyboard only | ✅ (automated) | axe on 25 page states: **0 violations of any severity**; `keyboard.spec.ts`. A by-hand screen-reader pass is suggested (§8) |
| 4 | A user never sees another organization's data | ✅ | `tenant-boundary.spec.ts`: outsider gets "Page not found" on overview, members, settings, connections and a connection; API answers 404. Backend tenant-isolation suite unchanged and passing |
| 5 | Lint, format, strict types, unit coverage ≥ 85 %, e2e suite, backend `make check` | ✅ | §5 |
| 6 | Docs updated; report lists changes, deviations, deleted files and limitations | ✅ | This report; README, SECURITY §11, PROJECT_STATUS, ROADMAP, AI_CONTEXT. **Deleted files: none** (A1) |

## 4. Security controls (plan §7) — how each is verified

| Control | Verified by |
|---|---|
| No secrets in browser or Next.js server; build refuses non-local `http` API address | `public-config` unit tests; build refusal checked (1C-08) |
| Nonce CSP with `strict-dynamic`, `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`, `form-action 'self'` | `proxy` unit tests; e2e checks the header **and** that every script carries the response's nonce; zero CSP violations in all e2e runs |
| Other headers (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`) | e2e `security.spec.ts` |
| No browser storage; no `dangerouslySetInnerHTML`, `eval`, inline styles, `document.cookie` | ESLint rules + source-rules test; e2e storage checks |
| CSRF token in memory; session cookies HttpOnly + SameSite | API-client unit tests; e2e `security.spec.ts` |
| `next` validated (relative only) | unit tests; e2e unsafe-`next` test |
| Email-link tokens from the fragment, removed at once, sent once | unit tests; e2e (verify, reset, invitation) |
| Platform sign-in only to `https`; callback values validated | unit tests (1C-07) |
| Errors → friendly text + request ID; raw server details never shown | error-mapping tests incl. a scan of every backend error code |
| `npm audit` gate (production, high/critical) | `npm run check`, CI |

## 5. Test results

| Suite | Result |
|---|---|
| Frontend unit/component (Vitest) | **247 passed** · 98.1 % statements, 91.5 % branches, 98.4 % functions, 99.2 % lines (gate 85 %) |
| End-to-end + accessibility (Playwright + axe) | **9 passed** · axe 0 violations on 25 page states · 0 CSP violations · 0 script errors |
| Static | ESLint (0 warnings), Prettier, strict `tsc`, API-type drift tests: pass |
| Production dependency audit | 0 vulnerabilities |
| Backend `make check` | ruff, mypy --strict, **281 passed**, 98.42 % coverage (95 % gate on security-critical modules met) |

## 6. CI and Docker (plan §10)

- CI jobs: `lint-type`, `test`, `security` (existing) + **`frontend`** (install, lint, format, types, drift + unit tests with coverage, audit, build) + **`e2e`** (PostgreSQL, Redis, Mailpit, migrations, API, worker, built web app, Playwright with axe; report and logs uploaded on failure) + **`docker`** (API and web images). Checked with `actionlint`.
- `infrastructure/docker/web.Dockerfile`: Node 24, multi-stage, standalone output, non-root user, API address as a build argument. `docker compose up --build` now also starts `web` on port 3000.

## 7. Defects found during Phase 1C (all fixed)

Found by browser testing and the new suite; each now has a test.
- 1C-02: `HTTP_ERROR` had no message; the error-code scan missed some declarations.
- 1C-05: a second invitation link in the same tab was ignored; tables widened the page on phones; the table scroll area was not keyboard-focusable.
- 1C-06: a wrong current password signed the person out (every 401 was treated as "session ended").
- 1C-08: signing out inside an organization page kept a return address to it, so the next person on that browser was sent there; the Overview page's text was out of date after 1C-07.

## 8. Deviations from the plan

Each task's deviations are listed in `PHASE_01C_PROGRESS.md`. The ones that matter most for review:
1. **ESLint 10** instead of 9 (9 is end-of-life); Next.js's lint plugins verified to run under it (1C-01).
2. **Explicit "Accept invitation" click**; new invitees reopen the invitation link after verifying their email, because the token is never stored (1C-05).
3. **Members cannot leave an organization themselves** unless they are an owner or admin, because the API requires `members.manage` (1C-05) — a product decision for later.
4. **`GET /providers`** is available to any signed-in user (plan said "authenticated") and includes `auth_scheme` and `test_only` (1C-03).
5. **Keyboard pass is automated**; a by-hand screen-reader pass has not been done (1C-08).
6. **End-to-end tests run in Chromium only** (1C-08).
7. **CI raises sign-up/sign-in rate limits for its throwaway stack only**, because the suite creates 8 accounts from one address (1C-08).
8. **Root `.dockerignore`** added (1C-08).

## 9. Not verified in this environment

- **GitHub CI.** The workflow runs on pull requests and on pushes to `main`; pushing `feature/phase-1a` alone does not start it. Opening a pull request `feature/phase-1a → main` runs all jobs, including the new `e2e` and `docker` jobs.
- **Docker image build.** Docker Hub is blocked here, so the web image was not built; its steps were rehearsed in a clean folder (clean install, build, standalone server serving pages, nonce CSP and static files). The CI `docker` job builds it.
- Locally the e2e suite used a pre-installed Chromium 141; CI installs Playwright's own Chromium.

## 10. Known limitations and remaining risks

| Item | Severity | Note |
|---|---|---|
| Cross-site scripting would expose the in-memory CSRF token | HIGH (inherent) | Mitigated: nonce CSP with `strict-dynamic`, no raw HTML, React escaping, lint + source rules, e2e CSP checks |
| Cookies across `app.` / `api.` in final hosting | MEDIUM | Same registrable domain required; decide with hosting (Q16) |
| Dev-only `braces` advisory (5 "high" in the lint tool chain) | LOW | Not in the production bundle; no fixed version exists; re-check at each phase |
| Signed-out pages log a 401 in the browser console (`/auth/me` is how "signed out" is detected) | LOW | A 200 "session status" endpoint could remove it (backend change, not made) |
| Device names are worked out from the raw browser string | LOW | A backend summary would be cleaner |
| UI permission checks could drift from the API | LOW | UI checks are cosmetic; API decides; e2e covers role differences |
| Audit-log viewer | — | Deferred (decision 6); API available to owners/admins |

## 11. Rollback

The web app is a separate application. Removing the `web` service, `web.Dockerfile` and the `frontend`/`e2e` CI jobs restores the 1B state; the 1C-03 backend changes are additive and covered by tests.

## 12. Next

1. Product owner reviews Phase 1 (1A, 1B, 1C) — reports `PHASE_01A_REPORT.md`, `PHASE_01B_REPORT.md`, this report.
2. Open a pull request `feature/phase-1a → main` so GitHub CI runs every job, including end-to-end and Docker.
3. Start external approvals now (they set the calendar for Phases 2A–4): Shopify Partner account + development store, Google Ads developer token, Meta app review.
4. Phase 2A (Shopify, read-only) starts only after its plan is approved.
