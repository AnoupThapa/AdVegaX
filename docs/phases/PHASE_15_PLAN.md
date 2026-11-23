# Phase 15 — Production Readiness & Staging: Implementation Plan

**Status:** ✅ **Approved 2026-10-28 (A34: Fly.io Sydney, Amazon SES, 90-day retention with audit 7 years, the rest as recommended).** In progress. · **Date:** 2026-10-28

> Every feature phase (1 – 14) is built. Before the first paying customer, AdVegaX needs a **staging server** that runs exactly like production, and the **production-readiness gate** from the roadmap: security review, load test, backup and restore drill, and a staging soak. This phase prepares all of it in the repository and on staging; you approve the hosting and providers first.

**Depends on:** Phases 1 – 14. **Governing:** ROADMAP §2 (production-readiness gate), Q15 (retention, languages, currencies), Q16 (hosting and email), SECURITY.md.

## 1. Decisions needed from you

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-15-1** | Hosting | **Fly.io, Sydney region**: API, background worker and scheduler as separate machines from the existing Docker image; the web app on Fly.io too (one provider, one region). Managed **Postgres** in Sydney (Fly Managed Postgres or Neon in AWS Sydney — chosen in Step 0 by which supports AdVegaX's three database roles and Row-Level Security unchanged). Managed **Redis** (Upstash, Sydney). | Australian customers and data; you already have Fly.io on your computer; no code change to the Docker set-up. |
| **Q-15-2** | Email provider | **Amazon SES** (Sydney region) through the existing SMTP sender, with SPF, DKIM and DMARC on your domain; out of the SES sandbox before go-live. | Your choice (A34); cheapest at volume; no code change. |
| **Q-15-3** | Data retention | Keep everything while an organization is active; after an organization is closed or a store/connection removed, delete imported platform data after **90 days**; audit logs **7 years**; backups **35 days**. | Matches Australian record-keeping practice; Shopify's privacy webhooks already handled. Confirm with your accountant/lawyer. |
| **Q-15-4** | Launch languages and currencies | **English** only; reporting currencies as today (AUD, NZD, USD, NPR and the rest already supported); billing **AUD** (Phase 13). | Smallest safe launch. |
| **Q-15-5** | Domains | `app.advegax.com` (web) and `api.advegax.com` (API) — or the domain you own. | Separate origins, as the security set-up expects. |
| **Q-15-6** | Security review | Automated checks now (dependency audit, secret scan, container scan, OWASP ZAP baseline against staging) plus a **human penetration test by an outside firm** before taking payments (you choose the firm; quote needed). | The roadmap requires an independent review. |
| **Q-15-7** | Load test | **k6** script (no change to the app; run from your computer or CI) against staging: 50 organizations, 200 people, the daily imports and looks; targets p95 < 500 ms for pages' API calls, no errors. | Proves the sizing before customers arrive. |
| **Q-15-8** | Backups | Managed daily backups with point-in-time recovery; a **restore drill** on staging (restore into a new database, run the checks, record the time). Encryption keys kept outside the database and backed up separately. | A backup is only real once restored. |
| **Q-15-9** | Monitoring | Health checks, JSON logs to the host's log service, error alerts by email; **Sentry** for errors (free tier) — optional. | Know about problems before customers do. |
| **Q-15-10** | Delivery | Tasks 15-01 … 15-08 (§3), one report at the end with your checklist. Steps marked **(you)** need your accounts. | As every phase. |

## 2. Scope

- **Deployment files** in `infrastructure/`: Fly.io app definitions for api, worker, scheduler and web; release step running the database migrations with the migrator role; secrets set only in Fly.io's secret store (never in the repository).
- **Production settings check** extended (already refuses unsafe settings when deployed): billing and agency switches, Stripe keys only when billing is on, email provider set.
- **Data retention job** (Q-15-3): a scheduled, audited clean-up of data from closed organizations and removed connections after the retention period; off until switched on.
- **Runbooks** in `docs/runbooks/`: deploy and roll back, restore from backup, rotate keys, incident response, Stripe webhook set-up.
- **Security:** dependency and container scans in CI; ZAP baseline against staging; updated threat model in SECURITY.md.
- **Load test:** `scripts/load/` k6 script and results.
- **Staging soak:** two weeks on staging with the simulators off and your own test accounts (Step 0 of Phases 8 – 13 happens here).

**Non-goals:** going live with customers (needs your sign-off after the gate); multi-region; languages other than English.

## 3. Tasks

| Task | Content |
|---|---|
| 15-01 | Retention job, production settings check, health and monitoring hooks (code, tested) |
| 15-02 | Deployment files for Fly.io (api, worker, scheduler, web); release migrations |
| 15-03 | CI: dependency, container and secret scans |
| 15-04 | Runbooks (deploy/rollback, restore, key rotation, incidents, Stripe) |
| 15-05 | k6 load-test script |
| 15-06 **(you)** | Create the Fly.io, database, Redis and Amazon SES accounts; DNS for the domains; then I deploy staging |
| 15-07 **(you + me)** | On staging: restore drill, ZAP scan, load test, two-week soak with the live Step 0 checks |
| 15-08 | `PHASE_15_REPORT.md`: results and your go-live checklist |

15-01 … 15-05 can be built now; 15-06 and 15-07 wait for your accounts.

## 4. Rollback

Staging is separate from everything you use today; nothing in production exists yet. The retention job is off by default.

## 5. Approval checklist

Approve or change Q-15-1 … Q-15-10 and tasks 15-01 … 15-08.
