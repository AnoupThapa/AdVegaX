# AdVegaX — Security Implementation Notes

**Status:** Phase 1A (platform core & identity) · **Last updated:** 2026-10-08
**Governing decisions:** MASTER_SPECIFICATION §20 (D7, D10–D15) and §21 (A8–A12, A15); PROJECT_RULES §7, §13, §16A.

This document describes how the security requirements are implemented and tested. Specifications remain the source of requirements.

---

## 1. Authentication (identity domain)

| Control | Implementation | Code / tests |
|---|---|---|
| Password hashing | Argon2id (argon2-cffi defaults per RFC 9106); hashes upgraded on login when parameters change | `core/security/passwords.py` · `tests/unit/test_security_primitives.py`, `test_login_upgrades_outdated_password_hash` |
| Password policy | 12–128 characters (`PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_LENGTH`); must not equal the email; no composition rules | `password_policy_errors` |
| Account enumeration | Register, forgot-password and resend return identical responses; login failures are generic; unknown accounts still run a dummy hash verification | `identity/service.py` · `test_register_existing_email_is_indistinguishable`, `test_login_failures_are_generic` |
| Email verification | Single-use token (SHA-256 stored), `EMAIL_VERIFICATION_TTL`; unverified users may sign in but cannot create organizations or accept invitations | `test_verification_token_single_use_and_expiry`, `test_unverified_user_cannot_create_organization` |
| Password reset | Single-use token, `PASSWORD_RESET_TTL`; revokes all sessions; notification email | `test_forgot_and_reset_password_revokes_sessions` |
| Throttling | Redis fixed windows (§9 limits, all settings); fails **closed** (503) if Redis is unavailable unless `THROTTLE_FAIL_OPEN=true` | `core/security/throttle.py` · `tests/security/test_throttling.py` |
| Future methods | Credentials table separate from users; sessions record `auth_method` and `assurance_level` for later OAuth/SSO/MFA/passkeys | `identity/models.py` |

## 2. Sessions and cookies

- Session token: 256-bit random value; only its SHA-256 hash is stored (`sessions.token_hash`).
- Cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`, host-only on the API host; `Secure` and the `__Host-` name prefix are **required** in staging/production (startup fails otherwise).
- Lifetimes are configurable settings (A15): `SESSION_IDLE_TIMEOUT` (default 24 h, sliding), `SESSION_ABSOLUTE_TIMEOUT` (default 14 days, never extended), `SESSION_TOUCH_INTERVAL` (default 5 min). Validation: positive, idle ≤ absolute.
- Rotation on login and password change; revocation on logout, logout-all, password reset/change, and per session.
- Every request validates the session server-side (revoked, idle, absolute, user status).

Tests: `tests/api/test_auth.py` (`test_idle_and_absolute_expiry_use_settings`, `test_absolute_timeout_cannot_be_extended`, `test_login_rotates_session`, `test_session_cookie_attributes`, …).

## 3. CSRF, Origin and CORS

- **Signed double-submit token bound to the session.** `GET /auth/csrf` (and login/logout/password responses) return a token `nonce.HMAC(SECRET_KEY, nonce|session-binding)` and set the same value in an HttpOnly cookie. The web app keeps the token in memory (never `localStorage`) and sends it as `X-CSRF-Token`. Because the app (`app.`) and API (`api.`) are different hosts, the app cannot read API cookies, so the token is delivered in the response body.
- A state-changing request passes only if: Origin (or Referer) is in `CORS_ALLOWED_ORIGINS`, the header equals the cookie, and the signature matches the request's current session (or "anonymous" before login). Login and registration are protected (login CSRF).
- Unsafe requests with a body must be `application/json` (415 otherwise) and at most `MAX_REQUEST_BYTES` (413).
- CORS: explicit allowlist with credentials; `*` and non-https origins are rejected at startup in staging/production.

Tests: `tests/security/test_http_security.py`.

## 4. Authorization and tenant isolation

Layers (D12): authentication → organization membership → organization role → tenant context → repository scoping → PostgreSQL RLS.

- The URL `organization_id` is a claim. `resolve_tenant` checks an **active** membership in an **active** organization; otherwise **404** (existence is not revealed).
- `authorize(context, permission, resource)` is deny-by-default against a central matrix (API §24); a resource from another tenant raises 404. MVP authorization is organization-level (A7); the resource argument allows future per-resource grants.
- Role rules: only Owners grant/remove Owner; nobody assigns above their own rank; the last active Owner cannot be removed, demoted or suspended (owner rows are locked to serialize concurrent changes).
- Invitation acceptance derives the organization from a server-validated single-use token and requires the signed-in user's verified email to match.

### PostgreSQL roles and RLS

| Role | Purpose | Attributes |
|---|---|---|
| `advegax_migrator` | Owns the schema; Alembic only | NOSUPERUSER, NOBYPASSRLS, never used at runtime |
| `advegax_app` | API runtime | NOSUPERUSER, NOBYPASSRLS, not owner |
| `advegax_system` | Worker/system tasks (email outbox) | NOSUPERUSER, NOBYPASSRLS, narrow grants |

- RLS is enabled **and forced** on organizations, memberships, invitations, audit_logs, security_events and email_outbox.
- Context is set per transaction with `set_config(..., true)` (`app.current_org_id`, `app.current_user_id`); policies fail closed when it is unset. Session-level `SET` is forbidden (source test).
- Grants: identity tables SELECT/INSERT/UPDATE for the app role (no DELETE); audit_logs SELECT/INSERT only; security_events and email_outbox INSERT only for the app role and SELECT (+UPDATE for the outbox) for the system role.
- No `SECURITY DEFINER` functions (source test).

Tests: `tests/security/test_tenant_isolation.py` (route sweep generated from OpenAPI), `tests/security/test_rls.py`, `tests/migrations/test_migrations.py` (RLS catalog and role checks).

### Accepted design decision: global identity tables without RLS

`users`, `user_password_credentials`, `sessions` and `user_action_tokens` are not tenant-owned and are read before any user or organization context exists (login by email, token lookup). They have no RLS. Mitigations: accessed only through the identity domain; organization endpoints expose other users only through membership joins; route-sweep and unit tests cover exposure.

## 5. Audit and security events

- `audit_logs` is append-only (no UPDATE/DELETE/TRUNCATE for runtime roles). Records actor, organization, action, resource, result, correlation ID and scrubbed before/after values for organization, membership and invitation changes.
- `security_events` records authentication events with a keyed hash of the IP address (raw IPs are never stored) and a truncated user agent.
- Known limitation: an authorization **denial** raises inside the business transaction, so it is written to structured logs (`authorization_denied`) rather than `audit_logs`. A separate-transaction audit for denials can be added in a later phase.

## 6. Transactional email

- Domains call the notifications service; it writes an outbox row in the same transaction and dispatches after commit (Celery). The worker renders the template and sends through a vendor-neutral sender port (SMTP adapter).
- Single-use links use `APP_BASE_URL` and put the token in the URL **fragment** (`#token=`), so it is not sent to servers in request logs or `Referer` headers.
- The outbox payload is cleared once the email is sent or permanently fails; the API role cannot read the outbox.
- Retries use exponential backoff (`EMAIL_RETRY_BASE_DELAY`) up to `EMAIL_MAX_ATTEMPTS`. Until the Phase 1B scheduler exists, `python -m app.workers.email_tasks` delivers any due emails.

## 7. Secrets, configuration and logging

- Secrets come only from the environment (development) or a managed secret store (staging/production). `.env` files are git-ignored; `.env.example` holds names and harmless local defaults only.
- Staging/production startup refuses: default or short `SECRET_KEY`, insecure cookies, non-`__Host-` cookie names, wildcard or non-https CORS origins, non-https `APP_BASE_URL`, in-memory email, eager task execution.
- Logs are JSON with a correlation ID; keys resembling passwords, tokens, secrets, cookies, sessions, CSRF values or authorization headers are redacted. Errors return a generic envelope without stack traces or submitted values.
- Response headers: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, restrictive CSP; HSTS when deployed.
- Outbound HTTP libraries are banned outside `providers/` (ruff rule + source test) until the SSRF-safe client arrives in Phase 1B.

## 8. Verification commands

```bash
make lint typecheck test   # ruff, mypy --strict, pytest with coverage gates (85 % overall, 95 % security-critical)
```

CI (`.github/workflows/ci.yml`) additionally runs gitleaks secret scanning, `pip-audit` and a Docker image build.
