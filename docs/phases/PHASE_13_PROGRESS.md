# Phase 13 — Progress (Stripe Billing & Entitlements)

Plan: `PHASE_13_PLAN.md` (approved 2026-10-27, A32, all recommendations Q-13-1 … Q-13-12 with the starting prices and limits). Built task by task; **one report for the whole phase** (`PHASE_13_REPORT.md`).

| Task | Status |
|---|---|
| 13-01 Step 0: Stripe test mode — setup command, subscribe, portal, failing card, Stripe CLI events | ⏸ Waiting for your Stripe test account and keys |
| 13-02 Migration 0024; plans, trial, complimentary organizations | ✅ Done |
| 13-03 Billing-provider interface; Stripe through the safe HTTP client; simulator; setup command | ✅ Done |
| 13-04 Webhooks (signature, once only, any order); nightly check | ✅ Done |
| 13-05 Entitlements and read-only mode, enforced across the features | ✅ Done |
| 13-06 API; emails; audit | ✅ Done |
| 13-07 Web app: Billing page, banner, limit messages | ✅ Done |
| 13-08 Tests, browser test, `PHASE_13_REPORT.md` | ✅ Done — Phase 13 awaiting review |

## 13-01 — Step 0

**Blocked:** needs a Stripe account in **test mode**, its secret key and webhook signing secret in the local settings file (never in chat or the repository), and `BILLING_ENABLED=true` there (plan §2A, §4.2).

## 13-02 — Data, plans and the trial

- **Migration 0024** (additive, reversible): `billing_accounts` (one per organization, tenant-owned, forced RLS; the system role reads only the Stripe ids, status and trial end), `billing_events` and `billing_reconciliations` (system role only).
- **Plans** in `app/domains/billing/plans.py`: Starter AUD 49, Growth AUD 149, Scale AUD 399 a month; yearly = 10 × monthly; the limits you approved. Stripe prices are found by **lookup key** (`advegax_<plan>_<interval>`), so no Stripe id is in the code.
- **Trial:** 14 days of Growth, no card, starting when the organization is created while billing is on (or, for organizations that existed before, the first time they are used afterwards).
- **Complimentary:** organizations listed in `BILLING_COMPLIMENTARY_ORGANIZATIONS` have Scale limits and are never charged.

## 13-03 — Stripe

`billing/provider.py` (the interface, platform-independent) and `billing/stripe.py` (Stripe): prices by lookup key, Checkout Sessions (subscription mode, Stripe Tax on, the organization in the metadata), customer-portal sessions, reading subscriptions, creating products and prices. One fixed host through the safe HTTP client; the key only in the `Authorization` header; an idempotency key on every write; `Stripe-Version` when `STRIPE_API_VERSION` is set. Both shapes Stripe has used for a period end and an invoice's subscription are read. **Setup command:** `uv run python -m app.domains.billing.setup` creates only the missing prices (GST inclusive).

## 13-04 — Keeping in step with Stripe

`POST /api/v1/billing/stripe/webhook`: signature and age checked (refused events are not stored); each event recorded once by its id; the subscription is then **read from Stripe** and applied, so repeats and any order end in Stripe's current state; Stripe unreachable → 503 and Stripe sends it again. The **nightly check** (`BILLING_RECONCILE_INTERVAL`, run by the hourly billing tick) reads every known subscription and fixes differences, recorded in `billing_reconciliations`.

## 13-05 — Entitlements and read-only mode

One place (`billing/entitlements.py`) answers what is in force: off, complimentary, trialing, active, past due (grace of 7 days from the first failed payment) or **read-only**. Enforced on the server: linking a store or ad account, inviting a member (members and open invitations together), switching autopilot on, the AI runs a day. Read-only refuses every change under the organization except its billing, its own details and people, and switching things off or cancelling; the schedulers skip it (no imports, no daily look). Nothing is deleted.

## 13-06 — API, emails and audit

`GET /billing/plans`, `GET/POST /organizations/{id}/billing…` (API_SPECIFICATION §19N); owners only for Checkout and the portal (new permissions `billing.view`, `billing.manage`). Owner emails: trial ending (3 days before), payment failed (with the grace date), read-only, billing changed. Audit: checkout started, portal opened, subscription changed, read-only.

## 13-07 — Web app

**Billing** in the organization menu: where the organization stands in one sentence, usage against the limits, plans (monthly or yearly) with **Choose …** for owners (to Stripe Checkout), **Manage billing in Stripe** (the portal), a thank-you after Checkout. A banner on every organization page when the trial ends within 3 days, a payment failed or the organization is read-only. The new errors have plain messages.

## 13-08 — Tests and report

A Stripe simulator (`tests/stripe_sim.py`) behind the real HTTP client; API tests (trial, checkout and portal, roles, webhooks, the lifecycle, read-only, limits, the nightly check, setup), unit tests, page tests, the browser test (`e2e/billing.spec.ts`) and the report.
