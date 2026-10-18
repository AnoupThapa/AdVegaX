# AdVegaX — Security Implementation Notes

**Status:** Phase 1A (platform core & identity) + Phase 1B (integration foundation) · **Last updated:** 2026-10-08
**Governing decisions:** MASTER_SPECIFICATION §20 (D7, D10–D15) and §21 (A8–A12, A15, A16); PROJECT_RULES §7, §13, §16A.

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
- **Two exemptions:** `POST /api/v1/webhooks/{provider}` (2A-05) and `POST /api/v1/connections/{provider}/credentials` (2B-04). Both are exact path shapes, matched with a full regular expression, and skip only the Origin and CSRF checks, because platforms call them server to server. Size and content-type limits still apply, and tests prove that look-alike paths and every other POST are still checked.
  - **Webhooks** are authenticated by the platform's signature over the raw body.
  - **Key delivery** is authenticated by the single-use connect state echoed back (consumed at once). Further safeguards:
    - the request is rate-limited per address, limited to 4 KB, and nothing is echoed;
    - only `read` keys are accepted;
    - the key is verified **against the store recorded when the person started**, never an address from the posted body;
    - the membership and role are re-checked;
    - the outcome is shown only to the same signed-in person on their return.
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
| `advegax_system` | Worker/system tasks (email outbox, job claiming/recovery, key rotation) | NOSUPERUSER, NOBYPASSRLS, narrow grants |

- RLS is enabled **and forced** on organizations, memberships, invitations, audit_logs, security_events, email_outbox (1A) and external_connections, external_connection_credentials, external_resources, organization_resource_links, job_runs (1B).
- 1B child tables use composite foreign keys on `(organization_id, id)`, so a row cannot reference another tenant's parent even through a bug.
- Context is set per transaction with `set_config(..., true)` (`app.current_org_id`, `app.current_user_id`); policies fail closed when it is unset. Session-level `SET` is forbidden (source test).
- Grants: identity tables SELECT/INSERT/UPDATE for the app role (no DELETE); audit_logs SELECT/INSERT only; security_events and email_outbox INSERT only for the app role and SELECT (+UPDATE for the outbox) for the system role; 1B tables SELECT/INSERT/UPDATE (no DELETE) for the app role; the system role has SELECT/UPDATE on job_runs (claim/retry/recover) and on credentials (key rotation only). For scheduling only, the system role may read `stores` (0007) and four columns of `ad_accounts` (id, organization, platform, first-import time; 0013), never names or figures.
- No `SECURITY DEFINER` functions (source test).

Tests: `tests/security/test_tenant_isolation.py` (route sweep generated from OpenAPI), `tests/security/test_route_guards.py` (every route in the OpenAPI schema: 401 when signed out, 403 without CSRF, 422 for malformed IDs), `tests/security/test_rls.py`, `tests/migrations/test_migrations.py` (RLS catalog and role checks).

### Accepted design decision: global identity tables without RLS

`users`, `user_password_credentials`, `sessions` and `user_action_tokens` are not tenant-owned and are read before any user or organization context exists (login by email, token lookup). They have no RLS. Mitigations: accessed only through the identity domain; organization endpoints expose other users only through membership joins; route-sweep and unit tests cover exposure.

## 5. Audit and security events

- `audit_logs` is append-only (no UPDATE/DELETE/TRUNCATE for runtime roles). Records actor, organization, action, resource, result, correlation ID and scrubbed before/after values for organization, membership and invitation changes.
- `security_events` records authentication events with a keyed hash of the IP address (raw IPs are never stored) and a truncated user agent.
- **Refused actions (1B):** an authorization denial raises `AuthorizationDenied`; an exception handler writes an `authorization.denied` audit record (result `denied`, actor, organization, permission, resource) in a **separate transaction** after the business transaction rolls back. If that write fails, the failure is logged (`denial_audit_failed`) and the client still receives the normal 403.
- 1B audit actions: `connection.authorization_started`, `connection.created`, `connection.discovered`, `connection.health_changed`, `connection.revoked`, `resource.linked`, `resource.unlinked`, `resource.sync_requested`, `resource.synced`. Audit metadata never contains credentials, tokens, codes or provider error messages.

## 6. Transactional email

- Domains call the notifications service; it writes an outbox row in the same transaction and dispatches after commit (Celery). The worker renders the template and sends through a vendor-neutral sender port (SMTP adapter).
- Single-use links use `APP_BASE_URL` and put the token in the URL **fragment** (`#token=`), so it is not sent to servers in request logs or `Referer` headers.
- The web app reads the fragment token, removes it from the address bar immediately and never writes it to browser storage. An invitation token is held in memory only while a signed-out invitee signs in within the same tab; accepting requires an explicit click (1C-05).
- The outbox payload is cleared once the email is sent or permanently fails; the API role cannot read the outbox.
- Retries use exponential backoff (`EMAIL_RETRY_BASE_DELAY`) up to `EMAIL_MAX_ATTEMPTS`. The Phase 1B scheduler runs the delivery sweep every `SCHEDULE_EMAIL_SWEEP_INTERVAL`; `python -m app.workers.email_tasks` remains available for manual runs.

## 7. Secrets, configuration and logging

- Secrets come only from the environment (development) or a managed secret store (staging/production). `.env` files are git-ignored; `.env.example` holds names and harmless local defaults only.
- Staging/production startup refuses: default or short `SECRET_KEY`, insecure cookies, non-`__Host-` cookie names, wildcard or non-https CORS origins, non-https `APP_BASE_URL`, in-memory email, eager task execution.
- Logs are JSON with a correlation ID; keys resembling passwords, tokens, secrets, cookies, sessions, CSRF values or authorization headers are redacted. Errors return a generic envelope without stack traces or submitted values.
- Response headers: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, restrictive CSP; HSTS when deployed.
- Outbound HTTP libraries are banned outside `app/providers/http/` (ruff rule + source test); all outbound calls go through the SSRF-safe client (§9).
- Staging/production also refuse a non-https `API_BASE_URL` and the development `ENCRYPTION_KEYS`.

## 8. Credential encryption (Phase 1B, A16)

- **Envelope encryption.** Each credential set gets a fresh 256-bit data key; the secrets (JSON) are encrypted with **AES-256-GCM** and a random 96-bit nonce. The data key is wrapped (AES-256-GCM) by a versioned **key-encryption key** from the key ring.
- **Associated data** `advegax:credential:v1|<organization>|<connection>|<provider>` binds the ciphertext to its tenant and connection: ciphertext copied into another organization's row cannot be decrypted (`test_ciphertext_copied_to_another_tenant_cannot_be_decrypted`).
- **Key ring:** `ENCRYPTION_KEYS` (`"<version>:<base64 32 bytes>,…"`) and `ENCRYPTION_ACTIVE_KEY_VERSION`, behind a `KeyProvider` interface so a cloud KMS can replace the local ring when hosting is chosen (Q16). Deployed environments refuse the development key.
- **Rotation:** add a new key version, make it active, then run `python -m app.domains.integrations.rotation` (system role) — data keys are re-wrapped; ciphertext is unchanged; old versions can then be removed.
- **Stored:** ciphertext, wrapped data key, key version, provider, status, authorizing user, timestamps, granted scopes, external identifiers. **Never returned** through API responses, logs, audit records, errors or UI; decrypted only inside `app/domains/integrations/` (source test `test_credential_boundary`).
- **Disconnect** revokes at the provider where supported and erases ciphertext, wrapped key and key version (all three nulled together; check constraint). Unreadable or missing credentials surface as an expired connection, never as an error containing secret material.

## 9. Outbound requests — SSRF protection (Phase 1B, A11)

`app/providers/http/` is the only place allowed to make outbound HTTP requests.

| Control | Implementation |
|---|---|
| Scheme / URL | `https` only; credentials in URLs rejected; ports restricted to an allowlist (default 443) |
| Hostname | IDNA-normalized; IP literals in any form (decimal, octal, hex, short forms, IPv6) rejected; internal names (`localhost`, single-label, `.local`, `.internal`, `.localhost`, metadata names) rejected |
| DNS | Resolved by the client; **every** returned address must be public — loopback, private, link-local (incl. 169.254.169.254 metadata), CGNAT, multicast, reserved, unspecified, IPv6 ULA/link-local, and IPv4 embedded in IPv6 (mapped, NAT64, 6to4, Teredo) are blocked |
| DNS rebinding | Connection pinned to the validated IP; TLS SNI and `Host` keep the original name, so certificate validation still applies |
| Redirects | Not followed automatically; each `Location` re-validated (including DNS); cross-host redirects refused; maximum `OUTBOUND_MAX_REDIRECTS` (3); `Authorization`, `Cookie` and API-key headers stripped on redirect |
| Limits | `OUTBOUND_CONNECT_TIMEOUT`, `OUTBOUND_READ_TIMEOUT`, streamed `OUTBOUND_MAX_RESPONSE_BYTES` cap (also checks `Content-Length`); **whole-request deadline `OUTBOUND_REQUEST_TIMEOUT`** (60 s, 2B-03) so a server dripping its body slowly cannot hold a worker |
| Streaming downloads (2A-06) | `stream_lines` for platform bulk exports: **per-provider host allowlist** checked before connecting (Shopify: `SHOPIFY_BULK_DOWNLOAD_HOSTS`) on top of SSRF validation and pinning; no redirects; no credentials sent (pre-signed URL); limits `OUTBOUND_MAX_DOWNLOAD_BYTES`, `OUTBOUND_DOWNLOAD_TIMEOUT` and 16 MiB per line; memory stays at about one line. Signed result URLs are treated as secrets: never logged, stored or put in errors |
| Environment | `trust_env=False` — ambient proxy variables cannot redirect traffic |
| Errors | Blocked destinations raise `BlockedDestinationError` with a reason code only; timeouts/transport errors map to retryable provider errors |

Tests: `tests/security/test_ssrf.py` (81 cases).

**Merchant-supplied store addresses (WooCommerce, 2B-03, CRITICAL risk 6).** These rules sit on top of the controls above:
- **Address normalization** (`providers/woocommerce/stores.py`):
  - HTTPS only; a pasted `http://` address is refused, never silently upgraded;
  - no user name or password; port 443 only;
  - the host must pass the same public-name rules (IP literals in any notation and internal names are refused);
  - sub-folder paths limited to safe characters and 5 segments, with `..` refused; pasted `/wp-admin`, `/wp-json` and `/wp-login.php` tails are removed.
- **REST client** (`providers/woocommerce/client.py`):
  - HTTP Basic auth only; credentials are **never put in a URL** (WooCommerce's query-string fallback is not used, Q-2B-6);
  - **redirects are never followed** (`follow_redirects=False`), so credentials can only ever reach the stored address;
  - the public WordPress index is read without credentials;
  - routes are fixed paths built from the stored address;
  - errors carry codes only — response bodies are read solely for WooCommerce's fixed error identifier (bounded length) and never logged.
- DNS is re-validated on **every** request, so a store name that later resolves to an internal address is refused before any connection.

Tests: `tests/providers/test_woocommerce_client.py` (74 cases: addresses, auth, errors, paging, rebinding, internal resolution, redirects, huge and slowly dripping bodies).

## 10. Connect flow, provider calls and jobs (Phase 1B)

- **Connect state:** single-use, random, stored hashed in Redis with `CONNECT_STATE_TTL` (10 min) and consumed atomically (`GETDEL`); bound to the user, organization, provider and PKCE verifier. The callback takes the organization **only** from the state, re-checks that the signed-in user is the same and still has `connections.manage`, and redirects (303) to the app with a status code — never tokens. The redirect names the organization (`organization_id`) only after the state is validated and the user is re-confirmed as that organization's manager; it is omitted for an invalid state, a different or signed-out user, or a lost role (1C-03).
- **Provider list** (`GET /providers`): signed-in users only; public metadata (code, name, category, sign-in scheme, capabilities, test-only flag) — no configuration or secrets; empty in staging/production until Phase 2A. Redis errors fail closed (503).
- **PKCE (S256)** on every OAuth start.
- **Rate limiting:** Redis token bucket per provider (and key) before each provider call; an unavailable limiter is a retryable error.
- **Health:** auth failures mark the connection `expired`, permission failures `error`; both audited (`connection.health_changed`) with codes only.
- **Jobs:** handlers run under the job's tenant context, so a job cannot touch another tenant's rows (`test_job_cannot_cross_tenants`); errors stored as codes only; dead-letter after `JOB_MAX_ATTEMPTS`.
- **Fake provider:** registered only outside staging/production; the registry refuses test-only providers when deployed.
- **Shopify connect (2A-03):** read-only scopes; callback and install requests HMAC-verified (constant time) with the serving app's client secret; store address validated against Shopify's anchored pattern; the callback's `shop` must equal the shop held in the server-side state; installs older than 5 minutes refused (replay); client secrets only from settings (hidden from reprs and logs) and sent in the request body, never a URL; tokens encrypted at rest; response bodies never logged. **One live connection per platform account across organizations**, checked with a narrow system-role lookup *before* the token exchange (a second exchange would retire the first organization's token).
- **Webhook intake (2A-05):** signature verified (constant time) over the raw body **before** parsing; 401 and nothing stored on failure; deliveries triggered outside a 6-hour window (or more than 5 minutes in the future) refused as replays; redeliveries de-duplicated on the platform's webhook id. Only metadata is stored — never the body, so customer names, emails and addresses in payloads are never kept (Q8) — and it is deleted after 30 days. The account → organization lookup is a narrow system-role query; follow-up work (uninstall → revoke) runs as a tenant job. Privacy requests are recorded and audited (`privacy.request_received`) and carried out by jobs (2A-07): customer requests are answered as "no personal data held" and the customer id is removed from the log; `shop/redact` deletes every imported row for the store (audited with counts; skipped if the store was reconnected). Webhook bodies are never used as data — only the object id, whose current state is fetched from the platform.
- **Token lifecycle (2A-04):** access tokens are refreshed shortly before expiry (`TOKEN_REFRESH_MARGIN`); each refresh saves the new access **and** refresh token (rotation) encrypted; a keep-alive sweep (`SCHEDULE_TOKEN_REFRESH_INTERVAL`, singleton) refreshes connections idle for `TOKEN_KEEPALIVE_INTERVAL` so refresh tokens never lapse. Every refresh **and** every reconnect of the same platform account runs under one account lock (Redis `SET NX`, 60 s expiry, owner-checked release) and re-reads the credential row under `SELECT … FOR UPDATE`, so they never overlap. A refused refresh marks the connection `expired` ("Needs reconnecting"), audited with a code only. A platform-side revocation (Shopify `app/uninstalled`, received by webhook since 2A-05) revokes the connection, deletes its tokens and ends its links; imported data stays until the platform asks for erasure.

### Google Ads sign-in (Phase 3)
- Google's OAuth 2.0 flow with PKCE (S256) and single-use state; the verifier never leaves the server.
- The access and refresh tokens are encrypted at rest (§8). The developer token and the OAuth client secret live only in the secret store or the local untracked settings file. None of them appears in responses, logs, audit records, errors or the web app (journey and connect tests scan for them).
- Only the stable Google account id (`sub`) is kept, to recognise a reconnect; no email or name is stored.
- **Read-only by construction:** a static test allows only three Google Ads read methods in advertising providers, and refuses any write capability.
- Disconnect revokes the token at Google and always deletes our copy, even if Google cannot be reached.

### Meta sign-in (Phase 4)
- Facebook Login for Business with a configuration id (`ads_read`, `business_management`), PKCE (S256) and single-use state; the code is exchanged on the server for a long-lived token (about 60 days).
- **Secrets never in an address:** the token travels in the `Authorization` header and the app secret only in the body of the token exchange. Every Graph call carries `appsecret_proof` (HMAC-SHA256 of the token with the app secret). Meta's `debug_token` is not used, because it carries the token in the URL; the person and the permissions come from `/me` and `/me/permissions`.
- The token is encrypted at rest with its expiry date; the app secret lives only in the secret store or the local untracked settings file. None of them appears in responses, logs, audit records, errors or the web app (connect tests scan for them, including the HTTP client's request log).
- Only the person's Meta user id is kept, to recognise a reconnect; no name, email or picture is stored.
- **Read-only by construction:** every request passes one guard that allows `GET`, plus the token exchange, starting an insights report and removing AdVegaX's own permission — nothing that changes an ad account. Static tests check that the guard is the only way out and that `ads_management` is never requested.
- Disconnect removes AdVegaX's permission at Meta (`DELETE /me/permissions`) and always deletes our copy, even if Meta cannot be reached.

## 11. Web application (Phase 1C)

- **No secrets in the browser or the Next.js server.** The only configuration is the public API address; the build refuses a plain-`http` address that is not localhost.
- **Security headers:** a per-request nonce Content-Security-Policy (`default-src 'self'`, `script-src 'self' 'nonce-…' 'strict-dynamic'`, `frame-ancestors 'none'`, `base-uri 'none'`, `object-src 'none'`, `form-action 'self'`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, a minimal `Permissions-Policy`. Inline `style` attributes, raw HTML, `eval`, browser storage and `document.cookie` are rejected by lint and a source-rules test.
- **CSRF token in memory only**; session and CSRF cookies are `HttpOnly` and not readable by scripts. A 401 ends the local session except `INVALID_CREDENTIALS` (a wrong password).
- **Email-link tokens** are read from the URL fragment, removed from the address bar at once and sent once.
- **Return addresses** (`next`) are relative paths only. A deliberate "Sign out" goes to a plain sign-in page (no return address), so the next person on that browser is not sent to the previous person's page (1C-08).
- **Platform sign-in** is only followed to `https` addresses; values from the platform's return address are validated before use and removed from the address bar (1C-07).
- **Permissions in the UI are cosmetic**; the API decides. Another organization's pages show "not found", like the API's 404.
- **End-to-end checks (1C-08):** every run verifies the security-policy headers and script nonces, no security-policy violations or script errors on any page, nothing in browser storage or readable cookies, tokens removed from addresses, platform tokens never in the page, the tenant boundary, and an unsafe return address being ignored.

## 12. Verification commands

```bash
make lint typecheck test   # ruff, mypy --strict, pytest with coverage gates (85 % overall, 95 % security-critical)
make frontend-check        # ESLint, Prettier, strict TypeScript, Vitest with coverage, npm audit, build
make e2e                   # Playwright + axe against a running stack (see README)
```

CI (`.github/workflows/ci.yml`) additionally runs gitleaks secret scanning, `pip-audit`, the frontend checks, the end-to-end and accessibility suite against a real stack (PostgreSQL, Redis, Mailpit, API, worker, web), and Docker image builds for the API and the web app.
