# Phase 1C — Task Reports

Plan: `PHASE_01C_PLAN.md` (approved, A17). One report per task; the final `PHASE_01C_REPORT.md` follows task 1C-08.

| Task | Status |
|---|---|
| 1C-01 Scaffold, tooling, security headers + CSP, layout, design tokens | ✅ Done — awaiting review |
| 1C-02 API types + client | Not started |
| 1C-03 Backend: `GET /providers`, `organization_id` on callback redirect | Not started |
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
