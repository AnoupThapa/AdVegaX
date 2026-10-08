# Phase 1C — Task Reports

Plan: `PHASE_01C_PLAN.md` (approved, A17). One report per task; the final `PHASE_01C_REPORT.md` follows task 1C-08.

| Task | Status |
|---|---|
| 1C-01 Scaffold, tooling, security headers + CSP, layout, design tokens | ✅ Done — awaiting review |
| 1C-02 API types + client | ✅ Done — awaiting review |
| 1C-03 Backend: `GET /providers`, `organization_id` on callback redirect | ✅ Done — awaiting review |
| 1C-04 Auth pages | Not started |
| 1C-05 Organizations, members, invitations | Not started |
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

