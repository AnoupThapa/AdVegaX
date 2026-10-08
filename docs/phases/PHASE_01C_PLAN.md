# Phase 1C — Frontend Shell: Implementation Plan

**Status:** DRAFT — awaiting product-owner approval. No code before approval. · **Date:** 2026-10-08
**Depends on:** Phase 1A and 1B (implemented, pushed; awaiting review) · **Followed by:** Phase 2A (Shopify read-only + finance core)
**Governing documents:** MASTER_SPECIFICATION §2 (stack), §20–§21 (D7, D10–D15, A7, A8, A10); ARCHITECTURE §3–§4, §7; API_SPECIFICATION §3–§5, §24; PROJECT_RULES §4 (frontend); SECURITY.md §2–§3

---

## 1. Objective

A web app on top of the existing API, so a person can use everything built in 1A/1B without developer tools:

sign up → verify email → sign in → create or switch organization → invite members and manage roles → accept an invitation → manage own sessions and password → open the Connections page (list, connect result, resources, link/unlink, disconnect).

No new business rules in the browser: the API stays authoritative (ARCHITECTURE §4).

## 2. Scope

| Area | In scope |
|---|---|
| Project | `frontend/` — Next.js (App Router), React, TypeScript strict, Node 24 LTS, npm + committed `package-lock.json` |
| Typed API client | Types generated from the backend OpenAPI schema (committed); thin typed fetch client; CI fails if types drift from the API |
| Auth pages | Sign up, check-your-email, verify email, resend verification, sign in, sign out, forgot password, reset password |
| Organization | Create organization, organization switcher, organization settings (name), members (list, change role, remove), invitations (create, list, revoke), accept invitation |
| Account | Profile summary, sessions (list, revoke one, sign out everywhere), change password |
| Connections | List connections and status; connect-result messages; connection detail with discovered resources; link / unlink / link history; request sync and show job status; rediscover; disconnect — shown only to roles allowed by the API |
| Cross-cutting | CSRF handling, session-expiry handling, standard error display, loading/empty states, responsive layout, accessibility (WCAG 2.2 AA target), security headers + nonce-based CSP |
| Tests / CI | Unit + component tests, end-to-end tests against the real backend, automated accessibility checks, CI job, Docker image + compose service |
| Docs | ARCHITECTURE §4 as-built, README (frontend setup), SECURITY.md (frontend controls), PROJECT_STATUS, phase files, `PHASE_01C_REPORT.md` |

## 3. Non-goals

- Dashboards, analytics, products, campaigns, AI, billing UI (their phases).
- Any real platform connector (2A+). The Connections page works with whatever the registry offers — in deployed environments that is nothing yet.
- Audit-log viewer (API exists; deferred — see §15 decision 6).
- Internationalization, dark mode toggle, marketing site, social/enterprise login, MFA.
- Server-side rendering of signed-in data (see §4).

## 4. Key architecture decisions

### 4.1 Rendering and data flow **[Decision]**
The session cookie is host-only on the **API host** (`api.`), so the Next.js server on the **app host** (`app.`) never sees it. Therefore:
- Signed-in pages are **client components** that call the API directly from the browser (`credentials: "include"`); the API's CORS allowlist and session/CSRF checks remain the only gatekeepers.
- The Next.js server renders only the static shell and public pages; it holds **no secrets, no session, no API credentials** and never proxies API calls.
- Alternative (not recommended): a backend-for-frontend proxy in Next.js with cookies on the app host — duplicates the security boundary built and tested in 1A.

`app.` and `api.` share a registrable domain, so `SameSite=Lax` cookies are sent (same-site). Locally `localhost:3000` → `localhost:8000` is also same-site.

### 4.2 CSRF and session handling
- On load, the client calls `GET /auth/csrf` and keeps the token **in memory only** (never `localStorage`/`sessionStorage`); responses that return a fresh token replace it.
- Every unsafe request sends `X-CSRF-Token`. On `CSRF_FAILED`, fetch a new token and retry **once**.
- `401 UNAUTHENTICATED` → clear cached data and go to sign-in with a validated `next` parameter (relative paths only — no open redirects).

### 4.3 Email links and tokens
Backend links put the token in the URL **fragment** (`/verify-email#token=…`, `/reset-password#token=…`, `/invitations/accept#token=…`). The page reads the fragment client-side, **removes it from the address bar immediately** (`history.replaceState`), then posts it to the API. Tokens never reach Next.js server logs or `Referer` headers.

### 4.4 Routing

```text
/sign-in  /sign-up  /check-email  /verify-email  /forgot-password  /reset-password
/invitations/accept
/connections                     ← platform callback landing (redirects into the right organization)
/orgs/new
/orgs/[organizationId]/          → overview (empty state for future dashboards)
/orgs/[organizationId]/members
/orgs/[organizationId]/settings
/orgs/[organizationId]/connections
/orgs/[organizationId]/connections/[connectionId]
/account/security                (sessions, password)
```

The organization in the URL is a claim; the API decides (non-members get 404 → "not found" page).

### 4.5 Data fetching **[Decision]**
TanStack Query for caching, loading/error states and invalidation after mutations (mutations never auto-retry). Alternative: hand-written hooks (more code, more bugs).

### 4.6 Styling and components **[Decision]**
CSS Modules + CSS custom properties (design tokens) — built into Next.js, no new dependency. Small in-house accessible components (button, field, form errors, table, dialog using native `<dialog>`, toast, menu). Alternative: Tailwind CSS (extra dependency and build tooling).

### 4.7 Permissions in the UI
Buttons are shown or hidden from the user's role in `GET /auth/me` memberships, mirroring API §24 — **for usability only**. Every action is still authorized by the API; a hidden button is never the protection.

### 4.8 Data availability (A10)
No metrics are shown in 1C. The shared formatting helpers (`formatMetric`) render non-available values as their state ("Not available", "Not supported", "Not synced yet"), never 0, so later phases inherit the rule.

## 5. Dependencies **[Decision]**

Versions checked on the npm registry on 2026-10-08; exact patch versions are pinned in the lockfile when work starts.

| Package | Version | Purpose |
|---|---|---|
| `next` | 16.4.x | Framework (App Router) |
| `react`, `react-dom` | 19.3.x | UI |
| `typescript` | 6.0.x | Strict type checking. **Not 7.0** — `typescript-eslint` currently supports TypeScript < 6.1 |
| `openapi-typescript` (dev) | 7.13.x | Generate API types from the backend OpenAPI schema |
| `openapi-fetch` | 0.17.x | Small typed fetch client using those types |
| `@tanstack/react-query` | 5.x | Server-state cache (§4.5) |
| `eslint`, `eslint-config-next`, `typescript-eslint`, `prettier` (dev) | current | Lint and format |
| `vitest`, `@vitest/coverage-v8`, `jsdom`, `@testing-library/react` (dev) | current | Unit and component tests |
| `@playwright/test`, `@axe-core/playwright` (dev) | 1.64.x / 4.13.x | End-to-end and accessibility tests |

Runtime: **Node.js 24 LTS**. No UI kit, no CSS framework, no form or validation library.

## 6. Backend changes (small) **[Decision]**

| Change | Why |
|---|---|
| `GET /providers` (authenticated) → list of registered providers: `code`, `category`, display name, capabilities | The UI must not hard-code platforms. Locally it lists the fake platform; in staging/production it is empty until 2A, so the page shows "No platforms available yet" |
| Platform callback redirect adds `organization_id` (when known) | The callback landing page can open the right organization; without it the UI must guess |
| `display_name` on providers | Human-readable label |

Each is covered by API tests and the tenant-isolation route sweep. No database changes. No other API changes.

## 7. Security controls

| Control | Design |
|---|---|
| Secrets | None in browser code or the Next.js server. Only `NEXT_PUBLIC_API_BASE_URL` (public) is configured |
| CSP | Per-request nonce set in `proxy.ts` (Next.js 16): `default-src 'self'`; `script-src 'self' 'nonce-…' 'strict-dynamic'`; `connect-src 'self' <API origin>`; `frame-ancestors 'none'`; `base-uri 'none'`; `form-action 'self'`; `object-src 'none'` |
| Other headers | HSTS (deployed), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` minimal, `X-Frame-Options: DENY` |
| Storage | No tokens, CSRF values or personal data in `localStorage`, `sessionStorage` or non-API cookies |
| Redirects | `next` parameter validated (relative paths only) |
| Rendering | No `dangerouslySetInnerHTML`; API messages shown as text; lint rule forbids it |
| Errors | Error envelope codes mapped to friendly text; raw server details never shown; request ID shown for support |
| Clickjacking / framing | `frame-ancestors 'none'` |
| Dependencies | `npm audit` in CI (fail on high/critical); lockfile committed |
| Deployed config | Build refuses an `http://` API URL when `NODE_ENV=production` and the deployment is not local |

## 8. Accessibility

WCAG 2.2 AA target: semantic HTML and landmarks, labelled form fields with linked error messages, visible focus, keyboard-only operation, focus moved to headings on route change and to the first error on failed submit, colour contrast ≥ 4.5:1, `prefers-reduced-motion` respected. Automated axe checks on every page in end-to-end tests (zero serious/critical violations); manual keyboard pass recorded in the report.

## 9. Testing strategy

| Suite | Content | Gate |
|---|---|---|
| Unit / component (Vitest + Testing Library) | API client (CSRF retry, 401 handling, error mapping), `next` validation, fragment-token handling, role-based visibility, `formatMetric` availability rule, forms | Coverage ≥ 85 % of `lib/` and `features/` |
| End-to-end (Playwright, real backend + PostgreSQL + Redis + Mailpit) | Full journey: sign up → read verification email from Mailpit → verify → sign in → create organization → invite → accept as second user → change role → connect fake platform → link resource → sync → unlink → disconnect → sign out; password reset; session revoke; tenant boundary (user B cannot open org A URLs → not found); CSRF token in memory only | All pass |
| Accessibility | axe on every page in the journey | 0 serious/critical |
| Static | ESLint, Prettier check, `tsc --noEmit` strict, generated API types up to date | All pass |
| Security | No `localStorage`/`sessionStorage` use (source test), no `dangerouslySetInnerHTML`, CSP header present with nonce | All pass |

## 10. CI

New `frontend` job: install (`npm ci`), lint, format check, type check, API-type drift check, unit tests with coverage, production build, `npm audit`. New `e2e` job: starts PostgreSQL, Redis, Mailpit, API, worker and the built frontend; runs Playwright with axe. Docker: `infrastructure/docker/web.Dockerfile` (non-root, standalone output) and a `web` service in `docker-compose.yml`.

## 11. Tasks (for task-by-task implementation and review)

| Task | Content |
|---|---|
| 1C-01 | Scaffold `frontend/`, tooling (TS strict, ESLint, Prettier, Vitest), security headers + CSP in `proxy.ts`, layout and design tokens |
| 1C-02 | API types generation + drift check; API client (CSRF, 401, error mapping); query setup |
| 1C-03 | Backend: `GET /providers`, `organization_id` on callback redirect (+ tests) |
| 1C-04 | Auth pages (sign up, verify, resend, sign in/out, forgot/reset) |
| 1C-05 | Organizations: create, switch, settings, members, invitations, accept invitation |
| 1C-06 | Account security: sessions, sign out everywhere, change password |
| 1C-07 | Connections pages |
| 1C-08 | End-to-end + accessibility suite, CI jobs, Docker, docs, report |

Each task stops after it is complete and tested, with a short implementation report.

## 12. Acceptance criteria

1. The journey in §1 works in a browser against the real API, locally and in CI.
2. No token, CSRF value or secret is stored in browser storage, URLs (after load), logs or the Next.js server.
3. Every page passes axe with zero serious/critical violations and works with keyboard only.
4. A user can never see another organization's data through the UI (API returns 404; UI shows not found).
5. Lint, format, strict type check, unit coverage ≥ 85 %, end-to-end suite and backend `make check` all pass.
6. Docs updated; report lists changes, deviations, deleted files (A1) and limitations.

## 13. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Cross-site scripting would expose the in-memory CSRF token and allow actions as the user | HIGH | Nonce CSP with `strict-dynamic`, no raw HTML rendering, React escaping, lint rules |
| Next.js 16.4 is two days old | MEDIUM | Pin the latest 16.x patch at start; upgrade within 16.x only |
| Client-rendered signed-in pages (no SSR) | LOW | Acceptable for an authenticated app; public pages remain fast |
| UI permission checks drifting from the API matrix | LOW | UI checks are cosmetic; API is authoritative; e2e tests cover role differences |
| Cookie behaviour across `app.`/`api.` in the final hosting setup | MEDIUM | Same registrable domain required; documented for hosting (Q16) |

## 14. Rollback

Frontend is a separate application; removing the `web` service and the CI jobs restores the 1B state. The two small backend changes are additive and covered by tests.

## 15. Decisions requested with approval

| # | Item | Recommendation |
|---|---|---|
| 1 | Client-rendered signed-in pages calling the API directly; Next.js server holds no session (§4.1) | Approve |
| 2 | Dependencies in §5 (TypeScript 6.0, not 7.0; npm; Node 24 LTS) | Approve |
| 3 | TanStack Query for server state (§4.5) | Approve |
| 4 | CSS Modules + in-house accessible components; no UI kit or Tailwind (§4.6) | Approve |
| 5 | Backend additions in §6 (`GET /providers`, `organization_id` on callback redirect) | Approve |
| 6 | Audit-log viewer deferred to a later phase | Approve (API stays available to Owners/Admins) |
| 7 | WCAG 2.2 AA target with automated axe gate | Approve |
| 8 | Unit-test coverage gate 85 % for `lib/` + `features/` | Approve |
| 9 | Task-by-task delivery 1C-01 … 1C-08 with a report after each | Approve |
