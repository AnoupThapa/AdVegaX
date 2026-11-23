# Application inventory

Built from the repository at `409ac5a` and the running local stack. The figures were measured, not copied from documentation.

## Architecture and stack

| Layer                            | Technology                                                                                                                                                         | Where                                                                                     |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Web app                          | Next.js 16 (App Router, standalone server), React, TypeScript strict, CSS Modules with design tokens, TanStack Query                                               | `frontend/` (≈30,000 lines in `app`, `features`, `components`, `lib`)                     |
| API                              | FastAPI, Python 3.12, Pydantic, SQLAlchemy 2                                                                                                                       | `backend/app/` (≈43,900 lines, 263 type-checked files)                                    |
| Database                         | PostgreSQL 16 with **forced Row-Level Security** and three roles: `advegax_migrator` (DDL), `advegax_app` (requests), `advegax_system` (jobs). None has BYPASSRLS. | `backend/alembic/versions/0001…0027`, `infrastructure/docker/postgres/init/001_roles.sql` |
| Background work                  | Celery worker and beat, Redis broker; durable `job_runs` and `email_outbox` tables                                                                                 | `backend/app/workers/`                                                                    |
| Cache, limits, short-lived state | Redis: throttles, OAuth `state` (single use, via `GETDEL`), admin step-up flags                                                                                    | `app/core/security/throttle.py`, `app/domains/integrations/connect_state.py`              |
| Secrets at rest                  | Envelope encryption (versioned keys, associated data) for platform tokens, Admin-portal keys and TOTP secrets                                                      | `app/core/security/encryption.py`, `app/domains/platform/store.py`                        |
| Hosting (planned)                | Fly.io Sydney: two API machines (1 GB), worker (512 MB), two web machines; health check `/api/v1/health/ready`                                                     | `infrastructure/fly/*.toml`, `docs/runbooks/`                                             |
| Desktop install                  | Windows PowerShell scripts (setup, start, stop, shortcuts, make-admin, reset-demo)                                                                                 | `scripts/windows/`                                                                        |

## Backend domains (26)

actions, advertising, agency, ai, analytics, audit, autopilot, billing, builder, commerce, creative, finance, funnel, fx, identity, integrations, jobs, metrics, notifications, optimization, organizations, platform (admin), retention, strategy, webhooks.

## API endpoints

There are **143** documented operations in `frontend/lib/api/openapi.json`. Another **5** are deliberately left out of the schema: the OAuth callback, the WooCommerce credential post, the Shopify install, the platform webhooks and the Stripe webhook.

| Group                               | Count | Group                | Count |
| ----------------------------------- | ----: | -------------------- | ----: |
| creatives                           |    15 | advertising          |     7 |
| auth                                |    13 | strategies           |     7 |
| connections                         |    12 | stores               |     6 |
| actions (changes)                   |    12 | agency               |     6 |
| organizations, members, invitations |    11 | autopilot            |     5 |
| campaign builder                    |    11 | analytics (GA4)      |     5 |
| admin portal                        |    11 | unified analytics    |     4 |
| recommendations                     |     8 | billing              |     4 |
| funnel                              |     3 | health, audit, other |     4 |

All organization routes go through `tenant_context` (`app/api/deps.py`). That check resolves membership, or an active agency grant, on the server; the organization id in the URL is treated only as a claim. While billing is on, read-only organizations may only call the routes in `READ_ONLY_ALLOWED`.

## Web routes (38 pages)

- **Public:** `/`, `/sign-in`, `/sign-up`, `/check-email`, `/verify-email`, `/forgot-password`, `/reset-password`, `/invitations/accept`, `/connect/[provider]`, `/connections`, `/robots.txt`.
- **Account:** `/account/security`, `/orgs/new`.
- **Organization** (`/orgs/[id]/…`): overview, reports, funnel, analytics (+ property), advertising (+ account, campaign), strategies (+ detail), creatives (+ set), builder/[draft], recommendations (+ detail), changes (+ detail), stores (+ store, products), connections (+ detail), members, settings, billing, clients (agency).
- **Operator:** `/admin`.

## Database (61 application tables)

action_events, action_settings, actions, ad_accounts, ad_budgets, ad_campaigns, ad_groups, ad_performance_daily, ad_sync_state, ads, agency_grants, ai_models, ai_runs, analytics_daily, analytics_properties, analytics_sync_state, audit_logs, autopilot_policies, autopilot_runs, billing_accounts, billing_events, billing_reconciliations, campaign_drafts, campaign_strategies, commerce_sync_state, creative_assets, creative_rules, creative_sets, creatives, email_outbox, external_connection_credentials, external_connections, external_resources, financial_daily, fx_rates, invitations, job_runs, memberships, optimization_settings, order_items, orders, organization_resource_links, organizations, platform_admins, platform_settings, product_cost_history, product_variants, products, prompt_versions, recommendation_outcomes, recommendations, refund_items, refunds, sales_entries, security_events, sessions, stores, user_action_tokens, user_password_credentials, users, webhook_events.

The schema has 121 foreign keys, 161 check constraints, 109 unique constraints and 192 RLS policies. Money columns are `NUMERIC(20,6)`. There are no float columns and every timestamp has a time zone.

## Authentication and roles

- **Sign-in:** email and password (Argon2id via argon2-cffi, `passwords.py`), with server sessions held in an HTTP-only cookie (`__Host-` prefix enforced when deployed).
- **CSRF protection:** a double-submit token bound to the session, plus an Origin check.
- **Accounts:** email verification, password reset, a list of active sessions with revocation, and sign-out everywhere.
- **Organization roles:** owner, admin, manager, analyst, viewer (`app/domains/organizations/permissions.py`).
- **Platform administrators:** a separate table (`platform_admins`) with a mandatory TOTP step-up lasting 12 hours.

## External integrations

Shopify (OAuth, bulk import, webhooks), WooCommerce (REST keys), Google Ads, Meta Ads, Google Analytics 4, Stripe (checkout, portal, signed webhooks), Anthropic (strategies, creatives and explanations, schema-validated), Amazon SES/SMTP, ECB FX rates. Each has an in-repo simulator used by the tests (`backend/tests/*_sim.py`).

## Scheduled jobs (Celery beat)

email_sweep, job_recovery, token_refresh, commerce_reconcile, commerce_deep, actions_sweep, optimization, ads_sync, fx_rates, analytics_sync, billing, retention, webhook_purge. Each runs as a singleton (`run_singleton`).

## Configuration

`backend/app/core/settings.py` (632 lines). Deployed environments refuse to start with:

- the development secret or encryption keys;
- insecure cookies;
- wildcard or non-HTTPS CORS origins;
- a non-SMTP email backend;
- eager Celery;
- incomplete Stripe settings;
- live Stripe keys in staging.

## Requirements documents compared

`docs/MASTER_SPECIFICATION.md`, `API_SPECIFICATION.md`, `DATABASE_SCHEMA.md`, `SECURITY.md`, `ARCHITECTURE.md`, `DESIGN_SYSTEM.md` and the phase plans and reports 00–17. One mismatch was found between the documents and the code (QA-016).
