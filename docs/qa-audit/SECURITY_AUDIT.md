# Security audit

The audit reviewed the code against OWASP ASVS 4 (levels 1–2) and the OWASP Top 10 (2021). It used the existing automated security tests and non-destructive local probes. **Active attack probing** (injection payloads, XSS fuzzing and role-escalation attempts beyond the existing tests) **was not approved** for this audit, so those areas are marked _Not Verified_ where the automated tests do not cover them.

## Summary

| Area                               | Result                                                                                        |
| ---------------------------------- | --------------------------------------------------------------------------------------------- |
| Authentication                     | Strong. One weak spot in the Admin step-up (QA-003, QA-013).                                  |
| Authorization and tenant isolation | Strong. Enforced in the database and in every route; see the tenant audit.                    |
| Session and CSRF                   | Strong                                                                                        |
| Secrets and configuration          | Strong. No secrets in the repository or its history.                                          |
| Dependencies                       | **One advisory** (QA-004)                                                                     |
| Injection, XSS, SSRF               | No issues found in review. SSRF and route-guard tests exist. Active probing was not verified. |

## Findings

| ID     | Sev | Finding                                                                     | Evidence                                                                             | Fix                                                      |
| ------ | --- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| QA-003 | P2  | No attempt limit on Admin two-step codes, and failures are not audited      | `app/domains/platform/service.py` `verify()` / `enable()` never call `throttler.hit` | Per-user and per-IP throttle, lockout, audit of failures |
| QA-004 | P2  | `certifi` advisory PYSEC-2026-4320                                          | `pip-audit --strict` exit 1                                                          | Upgrade to ≥ 2026.10.18                                  |
| QA-012 | P3  | A chunked request body is read whole into memory before its size is checked | `app/core/security/middleware.py:78-83`                                              | Streamed size check, or an edge limit verified on Fly.io |
| QA-013 | P3  | A two-step code can be reused within its 90-second window                   | `app/domains/platform/totp.py`                                                       | Remember the last accepted time step                     |
| QA-007 | P3  | 500 responses lose the request id                                           | DB-outage test                                                                       | Correlation middleware ordering                          |

## Controls verified

**Authentication** (`app/domains/identity`, `app/core/security`):

- Passwords are hashed with Argon2id (`passwords.py`) and never stored in plain text: there is a separate `user_password_credentials` table, and the runtime roles cannot read some protected tables (`test_runtime_roles_cannot_read_protected_tables`).
- A wrong password and an unknown email give the same 401 INVALID_CREDENTIALS (probe).
- Throttles cover sign-in per account+IP and per IP, registration, and email actions. The throttle **fails closed** when Redis is down (`THROTTLE_FAIL_OPEN=False`; probe: 503).
- Email verification is required for organization work (`require_verified`). Reset tokens are single-use (e2e `password-reset`).
- Sessions use server-side records with idle (24 h) and absolute (14 day) timeouts. Revoking one session or all of them works (e2e `sessions`, probe). Cookies are HTTP-only, and when deployed `Secure` and the `__Host-` prefix are required (settings validation).
- CSRF uses a session-bound double-submit token plus an Origin/Referer allow-list on every unsafe method (`RequestGuardMiddleware`; `test_every_unsafe_route_requires_the_csrf_token`; probes 403).
- The Admin portal needs a platform-admin record **and** a TOTP step-up for 12 hours. The TOTP secret is encrypted with associated data, and constant-time comparison is used.

**Authorization:**

- The organization id in a URL is only a claim. Membership or an agency grant is resolved on the server (`tenant_context`).
- Role checks are in `organizations/permissions.py` and enforced server-side.
- `test_every_org_route_returns_404_for_non_members` sweeps every organization route.
- `test_foreign_child_ids_under_own_org_return_404` covers identifier substitution.
- Billing read-only mode blocks writes on the server.

**Injection and XSS:**

- All SQL goes through SQLAlchemy with bound parameters. String-built SQL appears only in migration DDL and in three interval expressions built from integer-cast internal settings (`jobs/service.py:135,187`, `notifications/delivery.py:88`). None of these take user input. They could be rewritten as bound intervals for hygiene (P4).
- The web app uses no `dangerouslySetInnerHTML` or `eval`.
- A nonce-based Content-Security-Policy and HSTS are set in `proxy.ts`, plus `X-Content-Type-Options` (e2e `security`).
- AI output is schema-validated and never rendered as HTML.

**SSRF:** WooCommerce store URLs are checked (`tests/security/test_ssrf.py`), and the HTTP client is restricted (`app/providers/http`, 98% coverage gate).

**OAuth:**

- `state` is random, stored hashed and consumed once (`GETDEL`), with a time limit (`connect_state.py`, `test_connect_state.py`).
- Return addresses are validated (`lib/navigation/safe-next.ts`; e2e "sign-in ignores an unsafe return address").

**Webhooks:**

- Shopify uses HMAC, a replay window and a unique `webhook_id` for deduplication (`webhooks/service.py`).
- Stripe signatures are checked with a timestamp tolerance (`billing/stripe.py`), and events are deduplicated by `stripe_event_id`.

**Secrets:**

- No credential patterns were found in the full git history (Anthropic, Stripe live, AWS, Google, Slack, GitHub, Meta tokens and private keys were searched for).
- Only `.env.example` files are tracked. Deployed environments refuse the development secret or encryption keys.
- Platform tokens and Admin-portal keys use envelope encryption, and the Admin portal shows only the last four characters.
- Logs scrub secrets (`app/core/logging.py`; runbook note).

**CORS:** explicit `https://` origins are required when deployed (settings validation).

**File uploads (creatives):** type and size limits and EXIF/location stripping (`test_creative_images.py`). Files are private per organization.

**AI:** AI drafts strategies, creatives and explanations only. It cannot approve or send changes. Every change to an ad platform goes through the action engine with checks and human approval, or Autopilot within owner-set limits.

## Not verified

- Live penetration testing (planned as an outside test; QA-001).
- Fuzzing with injection or XSS payloads.
- Session fixation under a real proxy.
- The Fly.io edge configuration (TLS, body limits).
- Dependency audit of the transitive frontend dev tooling: only `--omit=dev` was audited, with 0 findings.
