# Runbook — Rotate keys and secrets

- **`ENCRYPTION_KEYS`** (platform credentials): add a new key version in front, keep the old ones; deploy; the rotation job re-encrypts (SECURITY.md); remove the old version only after it reports nothing left.
- **`SECRET_KEY`** (sessions, CSRF): changing it signs everyone out. Rotate after any suspected leak.
- **Database role passwords:** `ALTER ROLE … PASSWORD`, update the matching `DATABASE_URL_*` secret, deploy.
- **Stripe, Google, Meta, Anthropic, Amazon SES:** create the new key in the provider's dashboard, `fly secrets set`, deploy, then revoke the old key.
- Never paste a key into chat, a ticket or the repository; `gitleaks` runs on every push.
