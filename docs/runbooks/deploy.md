# Runbook — Deploy and roll back (Fly.io, Sydney)

Phase 15 (A34). Staging first; production is the same with the production app names.

## One-time set-up (you, with Claude)

1. **Accounts:** Fly.io; a managed Postgres in Sydney (Step 0 confirms it supports the three AdVegaX roles and forced Row-Level Security); Upstash Redis in Sydney; Amazon SES in `ap-southeast-2`.
2. **Database:** as the database's admin user run `infrastructure/docker/postgres/init/001_roles.sql`, then set a long random password for each role (`ALTER ROLE advegax_app PASSWORD '…'`, same for `advegax_system`, `advegax_migrator`) and run `scripts/bootstrap_db.sh advegax`. Passwords go only into Fly.io secrets.
3. **Amazon SES:** verify the sending domain (DKIM records), add SPF and DMARC, create SMTP credentials, request production access (out of the sandbox) before customers.
4. **Apps:** `fly apps create advegax-api-staging` and `fly apps create advegax-web-staging`; certificates: `fly certs add api-staging.<your domain>` and `fly certs add app-staging.<your domain>`, then the DNS records Fly.io shows.
5. **Secrets** — `fly secrets set --app advegax-api-staging NAME=value …` (never in chat, a file in the repository, or a ticket):
   - `SECRET_KEY` (64 random characters), `ENCRYPTION_KEYS` (generated as in SECURITY.md; **kept also in your password manager** — without it encrypted platform credentials cannot be read after a restore);
   - `DATABASE_URL_APP`, `DATABASE_URL_SYSTEM`, `DATABASE_URL_MIGRATOR`, `REDIS_URL`;
   - `SMTP_HOST=email-smtp.ap-southeast-2.amazonaws.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`;
   - `APP_BASE_URL`, `API_BASE_URL`, `CORS_ALLOWED_ORIGINS` (the web app's https origin);
   - platform and provider keys as each feature is switched on (`.env.example` lists every setting).
6. **Scheduler:** `fly scale count scheduler=1 --app advegax-api-staging` — exactly one.

## Deploy

```
fly deploy --config infrastructure/fly/api.fly.toml
fly deploy --config infrastructure/fly/web.fly.toml --build-arg NEXT_PUBLIC_API_BASE_URL=https://api-staging.<your domain>
```

The release step runs `alembic upgrade head` once; if it fails, nothing new starts. Check `https://api-staging.<your domain>/api/v1/health/ready` and sign in.

## Roll back

1. `fly releases --app advegax-api-staging`, then `fly deploy --image <previous image>`.
2. Migrations are additive; roll the schema back only if the release notes say so (`alembic downgrade <revision>` with the migrator URL), never in a hurry.
3. Feature switches (`BILLING_ENABLED`, `AGENCY_ENABLED`, `AUTOPILOT_ENABLED`, `ACTIONS_ENABLED`, `RETENTION_ENABLED`) turn features off without a deploy: `fly secrets set NAME=false`.
