# Phase 13 — Stripe Billing & Entitlements: Implementation Plan

**Status:** ✅ **Approved 2026-10-27 (A32, "Approve all": Q-13-1 … Q-13-12, with the starting prices and limits).** In progress — see `PHASE_13_PROGRESS.md`. · **Date:** 2026-10-27

> AdVegaX starts charging for itself. Customers choose a plan, pay through **Stripe Checkout**, manage their card and invoices in **Stripe's customer portal**, and AdVegaX enforces each plan's limits **in its own server code**. Built and tested against a **Stripe simulator** (no calls to Stripe in CI); Step 0 uses your Stripe account in **test mode**. This is AdVegaX's own billing — separate from any payment data a merchant connects.

**Depends on:** Phase 1 (organizations, owners, audit, email); the features whose use is limited (stores, ad accounts, members, AI runs, autopilot).

**Governing documents:** MASTER_SPECIFICATION (owner = billing; D14, D19 — billing is platform-independent); DISCOVERY_REPORT C9 (Shopify App Store billing only if that channel is added later); `phases/PHASE_13_BILLING.md` (outline).

---

## 1. Objective

Each organization is on a **plan**. A plan sets **limits** (stores, ad accounts, members, AI runs a day, whether autopilot is available). New organizations start a **free trial**. Owners subscribe, change plan or cancel; AdVegaX learns every change from Stripe through **verified webhooks** and a **nightly check**, and enforces the limits on the server. **Nothing a customer stored is ever deleted because of billing** — at worst the organization becomes read-only until it pays.

## 2. Decisions needed from you (plain language)

Each question has a recommendation. **Prices are your business decision** — the numbers below are placeholders to start with; change any of them.

| # | Question | Recommendation | Why |
|---|---|---|---|
| **Q-13-1** | Plans and prices | Three monthly plans in **AUD**, yearly at **10 × monthly** (2 months free):<br>• **Starter — AUD 49 / month:** 1 store, 2 ad accounts, 3 members, 10 AI runs a day, no autopilot.<br>• **Growth — AUD 149 / month:** 3 stores, 6 ad accounts, 10 members, 40 AI runs a day, autopilot.<br>• **Scale — AUD 399 / month:** 10 stores, 20 ad accounts, 30 members, 150 AI runs a day, autopilot.<br>Prices and limits live in AdVegaX's configuration, so you can change them without code. | Simple to sell; limits follow the real costs (AI and API use). |
| **Q-13-2** | Trial | **14 days of Growth**, no card needed. At the end, without a plan, the organization becomes **read-only** (everything visible, nothing new imported, no changes or AI) until an owner subscribes. | Lets merchants see value first; nothing is lost. |
| **Q-13-3** | Tax | **Stripe Tax**: Australian customers pay **GST (10 %) included** in the price shown; other countries as Stripe Tax decides. You register for GST collection in Stripe. | Correct invoices without AdVegaX doing tax maths. |
| **Q-13-4** | Currency | **AUD only** at launch; USD later. | One price list to maintain first. |
| **Q-13-5** | Who manages billing | **Owners only**: subscribe, change plan, cancel, open the portal. Everyone else sees the plan and its limits. | The owner is the account holder. |
| **Q-13-6** | Change and cancel | Upgrades take effect **at once** (Stripe prorates); downgrades and cancellations at the **end of the paid period**. | Fair and standard. |
| **Q-13-7** | Failed payment | Stripe retries automatically; the organization stays fully usable for **7 days** after the first failed payment, with a banner and owner emails; then **read-only** until paid. | Gives time to fix a card; no data loss. |
| **Q-13-8** | Over a limit | Checked **on the server** when adding a store, ad account or member, running AI, or switching autopilot on. After a downgrade, what exists **stays**; only adding more is refused (with the limit named). | Never breaks a working setup by surprise. |
| **Q-13-9** | Keeping in step with Stripe | Webhooks **verified by Stripe's signature**, processed **once** (event id) and **in any order** (AdVegaX reads the subscription's current state from Stripe for each event); a **nightly check** compares every subscription. | Billing must never drift. |
| **Q-13-10** | Your own businesses | An installation list of **complimentary organizations** (e.g. Eve Zone, Mediflex): Scale limits, never charged. | You use AdVegaX free. |
| **Q-13-11** | Shopify App Store billing | **Not in this phase** (C9): only needed if AdVegaX is ever listed in the Shopify App Store. | Not required for the web app. |
| **Q-13-12** | Delivery | Tasks 13-01 … 13-08 (§9), **one report at the end** with your review checklist. | As agreed for every phase. |

## 2A. What you need to set up (for Step 0 and real use)

1. A **Stripe account**; its **test-mode** secret key and webhook signing secret in the local settings file (never in chat or the repository).
2. AdVegaX's setup command creates the products and prices in Stripe test mode from the configuration (you can also see them in Stripe's dashboard).
3. For live use: Stripe **activated**, **Stripe Tax** with your GST registration, the customer portal enabled, a live webhook endpoint.

## 3. Scope

| Area | In Phase 13 |
|---|---|
| Provider | `app/domains/billing/`: a billing-provider interface (platform-independent, D19) and its **Stripe** implementation through the safe HTTP client (Checkout Session, customer portal session, read subscription, list subscriptions; idempotency keys). |
| Plans | Plans, prices and limits from configuration; the trial; complimentary organizations. |
| Entitlements | One function answers "may this organization do X?" from its plan and status; enforced where stores, ad accounts, members, AI runs and autopilot are added or used; read-only mode. |
| Webhooks | `POST /billing/stripe/webhook`: signature check, once-only by event id, out-of-order safe; checkout completed, subscription created/updated/deleted, invoice paid/payment failed. |
| Reconciliation | Nightly: every subscription read from Stripe and compared; differences fixed and logged. |
| Emails | Trial ending (3 days before), payment failed, read-only, subscription changed. |
| API | `GET /billing` (plan, status, limits, usage), `POST /billing/checkout`, `POST /billing/portal`, `GET /billing/plans`. |
| Web app | **Billing** page (owners act; others read): plan, trial or renewal date, usage against limits, choose a plan, manage in Stripe; banners for trial end, failed payment, read-only. |
| Data | Migration **0024** (§5). |

## 3A. Non-goals

- Usage-based (metered) prices; coupons beyond Stripe's own; invoices designed by AdVegaX.
- Agency billing for many client organizations (Phase 14).
- Shopify App Store billing (Q-13-11).
- Deleting data for non-payment.

## 4. Facts and Step 0

### 4.1 Facts (checked 2026-10-27)

1. **Stripe Checkout** in subscription mode creates the customer and subscription on Stripe's hosted page; AdVegaX never handles card numbers.
2. **The customer portal** lets customers update cards, see invoices, change or cancel plans as configured.
3. **Webhooks** carry a `Stripe-Signature` header to be verified with the endpoint secret; events can arrive more than once and out of order.
4. AdVegaX pins the Stripe **API version** it was built against.

### 4.2 Step 0 — live checks in Stripe test mode (task 13-01)

1. Run the setup command; check products and prices in the dashboard.
2. Subscribe with Stripe's test card; see the plan in AdVegaX; open the portal; change plan; cancel.
3. Use Stripe's failing test card; see the grace period, emails and read-only mode.
4. Send test events from the Stripe CLI (duplicates, wrong signature).

## 5. Data model (migration 0024)

- **`billing_accounts`** — one per organization: Stripe customer id, plan, status (`trialing` | `active` | `past_due` | `read_only` | `canceled` | `complimentary`), trial end, current period end, cancel at period end, first failed payment at, Stripe subscription id, updated at.
- **`billing_events`** — every webhook event received: Stripe event id (unique), type, received at, processed at, result — never card details.
- **`billing_reconciliations`** — each nightly check: when, accounts checked, differences fixed.

Tenant-owned with forced RLS where they belong to an organization; webhook intake runs with the narrow system role (as Phase 2A webhooks).

## 6. API

As §3. New errors:
- `PLAN_LIMIT_REACHED` (403, with the limit and the plan);
- `ORGANIZATION_READ_ONLY` (403);
- `BILLING_UNAVAILABLE` (503, Stripe not configured or not reachable).

## 7. Security

- No card data ever reaches AdVegaX (Checkout and portal are Stripe's pages).
- Stripe keys only in the local settings file; never logged, audited or returned.
- Webhooks: signature and timestamp checked, body size limited, processed once; refused events logged without their contents.
- Entitlements enforced on the server; the web app only explains them.
- Owners only for billing actions; every billing change audited.
- Tenant isolation: forced RLS; the route sweep covers every new route.

## 8. Testing

- **Stripe simulator:** Checkout, portal, subscriptions, invoices, signed webhooks.
- **Webhooks:** wrong or old signature refused; duplicates processed once; events out of order end in Stripe's current state; unknown events ignored.
- **Lifecycle:** trial → active; upgrade; downgrade at period end; payment failed → grace → read-only → paid → active; cancel → read-only at period end; complimentary.
- **Entitlements:** each limit at its edge; existing items kept after a downgrade; read-only blocks every change and AI run but not reading.
- **Reconciliation:** a missed webhook is corrected the next night.
- **Web app and browser:** page tests and one browser test with accessibility checks: trial banner, choose a plan (simulator Checkout), plan shown, limit reached message.

## 9. Tasks (one report for the whole phase)

| Task | Content |
|---|---|
| 13-01 | Step 0 (§4.2) — needs your Stripe test account |
| 13-02 | Migration 0024; plans, trial, complimentary organizations |
| 13-03 | Billing-provider interface; Stripe implementation; simulator; setup command |
| 13-04 | Webhooks (signature, once-only, any order); reconciliation |
| 13-05 | Entitlements and read-only mode, enforced across the features |
| 13-06 | API; emails; audit |
| 13-07 | Web app: Billing page, banners, limit messages |
| 13-08 | Tests, browser test, `PHASE_13_REPORT.md` with your review checklist |

## 10. Acceptance criteria

1. An owner subscribes, changes plan and cancels through Stripe; AdVegaX shows the right plan and dates.
2. Limits are enforced on the server; nothing existing is removed by a downgrade.
3. Duplicate, out-of-order and forged webhooks are handled safely; the nightly check corrects drift.
4. Trial end and failed payments lead to read-only mode after the stated grace, never to data loss.
5. No card data or Stripe key is ever stored, logged or shown.
6. All suites pass, with no calls to Stripe in CI.

## 11. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Billing state drifts from Stripe | HIGH | Webhooks read the current state; nightly reconciliation; audit |
| Customers blocked by mistake | HIGH | Grace periods; read-only rather than locked out; complimentary list; tests at every edge |
| Tax errors | MEDIUM | Stripe Tax; your accountant reviews the set-up |
| Forged webhooks | MEDIUM | Signature and timestamp checks; reading state from Stripe |

## 12. Rollback

`BILLING_ENABLED=false` (default until you switch it on): every organization keeps full use, as today. Migration 0024 is reversible.

## 13. Approval checklist

Approve or change:
- **Q-13-1 … Q-13-12** (especially the **prices and limits** in Q-13-1);
- Step 0 (§4.2);
- the data model (§5);
- delivery 13-01 … 13-08, with one report at the end of the phase.

No new library is needed (Stripe is called through AdVegaX's own safe HTTP client).
