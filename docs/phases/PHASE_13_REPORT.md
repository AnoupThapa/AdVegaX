# Phase 13 — Implementation Report (Stripe Billing & Entitlements)

**Status:** Implemented — awaiting your review. Step 0 (live checks in Stripe test mode, 13-01) waits for your Stripe test account and keys.
**Plan:** `PHASE_13_PLAN.md`, approved 2026-10-27 (A32, all recommendations, with the starting prices and limits).
**Progress log:** `PHASE_13_PROGRESS.md`.

## 1. Summary

AdVegaX can now charge for itself. **Billing stays off** (`BILLING_ENABLED=false`) until you switch it on; until then every organization keeps full use, exactly as before.

When it is on:

- every new organization gets a **14-day Growth trial**, no card needed;
- an **owner** chooses **Starter (AUD 49)**, **Growth (AUD 149)** or **Scale (AUD 399)** a month — or yearly at 10 × monthly — and pays on **Stripe Checkout**; GST is included for Australian customers (Stripe Tax);
- the card, invoices, plan changes and cancelling are in **Stripe's customer portal**; AdVegaX never sees card details;
- AdVegaX learns every change from **signed Stripe webhooks** and a **nightly check**, and enforces each plan's **limits on its own server**;
- a failed payment leaves **7 days** of full use, then the organization becomes **read-only**. So does a trial that ends without a plan. Read-only means everything stays visible but nothing new is imported, changed or generated. **Nothing is ever deleted.**

Your own businesses can be listed as **complimentary**: Scale limits, never charged.

## 2. What was delivered, by task

| Task | Delivered |
|---|---|
| 13-01 | ⏸ Step 0 — waiting (§10) |
| 13-02 | Migration 0024; plans and prices; the trial; complimentary organizations |
| 13-03 | Billing-provider interface; Stripe through the safe HTTP client; Stripe simulator; setup command for the prices |
| 13-04 | Webhook intake (signature, once only, any order); nightly check |
| 13-05 | Entitlements and read-only mode, enforced on the server across stores, ad accounts, members, AI runs, autopilot and the schedulers |
| 13-06 | Billing API (§19N); owner emails; audit |
| 13-07 | Billing page, banner, limit messages |
| 13-08 | Tests (§5), browser test, this report |

## 3. Acceptance criteria (plan §10)

| # | Criterion | Result |
|---|---|---|
| 1 | An owner subscribes, changes plan and cancels through Stripe; AdVegaX shows the right plan and dates | ✅ against the simulator (Step 0 confirms it live) |
| 2 | Limits enforced on the server; nothing existing removed by a downgrade | ✅ |
| 3 | Duplicate, out-of-order and forged webhooks handled safely; the nightly check corrects drift | ✅ |
| 4 | Trial end and failed payments lead to read-only after the stated grace, never to data loss | ✅ |
| 5 | No card data or Stripe key stored, logged or shown | ✅ |
| 6 | All suites pass, with no calls to Stripe in CI | ✅ (§5) |

## 4. Security controls

- **No card data** ever reaches AdVegaX: Checkout and the portal are Stripe's own pages.
- **Stripe keys** only in the local settings file; sent only in the `Authorization` header to `api.stripe.com`; never logged, audited, returned or put in an error.
- **Webhooks:** Stripe's signature (HMAC-SHA256) and a 5-minute age limit; a refused event is logged without its contents and **not stored**. Each event is recorded once by its id. AdVegaX then **reads the subscription from Stripe** rather than trusting the event's contents.
- **Entitlements on the server:** the web app only explains them.
- **Owners only** for Checkout and the portal (new permissions `billing.view` and `billing.manage`); every billing change is audited.
- **Tenants:** `billing_accounts` has forced RLS. The two event tables are for the system role only. The route sweep covers the new routes.

## 5. Test results

| Suite | Result |
|---|---|
| Backend `make check` (ruff, mypy, static rules, pytest) | ✅ 2,106 passed, coverage 95.35 % |
| Frontend `npm run check` (types, lint, format, Vitest) | ✅ 577 passed (branch coverage 85.4 %) |
| Browser (Playwright + accessibility) | ✅ 20 passed (new: `billing.spec.ts`). The whole suite now runs with billing **on** (and no Stripe key), so every earlier journey is also checked under the trial's limits |

New tests:

- `tests/api/test_billing_api.py`, 22 tests: trial, checkout and portal, roles, webhooks, the lifecycle, read-only, limits, the nightly check and setup;
- `tests/unit/test_billing_rules.py`;
- `tests/api/test_e2e_billing_seed.py`;
- `tests/stripe_sim.py` (the simulator);
- `frontend/tests/features/billing.test.tsx`;
- `frontend/e2e/billing.spec.ts`.

## 6. Database

Migration **0024** (additive, reversible) adds `billing_accounts`, `billing_events` and `billing_reconciliations`. See DATABASE_SCHEMA §14G.

## 7. New libraries

None. Stripe is called through AdVegaX's own safe HTTP client.

## 8. Defects found and fixed

- **Two simultaneous first visits to an organization could fail.** The first time an organization opened its autopilot settings (Phase 12), two requests at the same moment could both try to create the same record, and one failed. The browser test found it. Both the autopilot record and the new billing record are now created so the second request simply reads the first one's.
- **The simulator's event ids repeated between runs** against the same development database. They are now unique, as Stripe's are.

## 9. Deviations from the plan

1. **Where prices and limits live.** They are in one small file, `billing/plans.py`, rather than the settings file. A change there needs a release, and then the setup command creates the matching Stripe prices. This keeps Stripe's prices and AdVegaX's limits from drifting apart.
2. **When the trial starts.** For an organization created while billing is on, the trial starts at creation. For an organization that already existed when you switch billing on, the trial starts the first time it is used afterwards, so nobody is read-only on day one.
3. **Status words.** "Read-only", "complimentary" and the plan in force are worked out each time, from Stripe's own subscription status and your settings; they are not stored. The table keeps Stripe's word, for example `past_due`.
4. **Changing or cancelling a plan** happens in Stripe's portal: upgrades apply at once, downgrades and cancellations at the end of the period, as you configure the portal (§12 C). AdVegaX's own **Choose a plan** is only for an organization without a live subscription; otherwise it answers "use the portal" (`CONFLICT`).
5. **Members limit:** active members and **open invitations** count together, so an invitation cannot get round the limit.
6. **Read-only still allows** these actions:
   - billing;
   - the organization's name and settings;
   - managing members and invitations (adding still needs a free place);
   - stopping autopilot;
   - cancelling or rejecting a change;
   - rejecting advice;
   - disconnecting and unlinking.
7. **A cancelled subscription during the trial window** falls back to the trial until it ends.
8. **The browser tests run with billing on but no Stripe key.** **Choose a plan** is therefore refused there on purpose. The test subscribes through the in-process Stripe simulator instead.

## 10. Not verified in this environment — Step 0 (13-01)

1. Run the setup command against your Stripe test account. Check the six prices in Stripe's dashboard; they should include GST.
2. Subscribe with Stripe's test card. Then:
   - see the plan in AdVegaX;
   - open the portal;
   - change plan (an upgrade applies at once, a downgrade at period end);
   - cancel.
3. Use Stripe's failing test card. You should see the banner and the email, then read-only after the grace period. Pay again: full use returns.
4. Send test events from the Stripe CLI, including a duplicate and one with a wrong signature.
5. Pin `STRIPE_API_VERSION` to the version shown in your Stripe dashboard.

## 11. Known limitations

- **AUD only.** There is no metered pricing, and coupons only through Stripe itself.
- **No agency billing** for many client organizations (Phase 14). **No Shopify App Store billing.**
- **The trial-ending banner** counts from when the page was opened.
- **Emails** go to every active owner.

## 12. Your review checklist

**A. Decide or confirm (business):**

1. The **prices and limits**:
   - Starter AUD 49: 1 store, 2 ad accounts, 3 members, 10 AI runs a day, no autopilot;
   - Growth AUD 149: 3 stores, 6 ad accounts, 10 members, 40 AI runs a day, autopilot;
   - Scale AUD 399: 10 stores, 20 ad accounts, 30 members, 150 AI runs a day, autopilot;
   - yearly is 10 × monthly.
2. The **14-day Growth trial**, and the **7-day grace** after a failed payment.
3. **Owners only** manage billing.
4. Which organizations are **complimentary**, for example Eve Zone and Mediflex.
5. The deviations in §9, especially 2 (when the trial starts) and 6 (what read-only still allows).

**B. Try it in the app** (after Step 0, in Stripe test mode):

1. Open **Billing** in an organization's menu. Read the trial sentence and the usage table.
2. Choose **Starter**, pay with Stripe's test card `4242 4242 4242 4242`, and come back. The page shows "Starter plan, monthly. It renews on …".
3. Click **Manage billing in Stripe**. Change to Growth, then back to the Billing page.
4. Invite members until the limit. The next invitation is refused, and the message names the Billing page.
5. In the portal, cancel the plan. The page says when it ends.

**C. Set up when you are ready:**

1. A **Stripe account**. Put its test-mode secret key and webhook signing secret in the local settings file (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`), never in chat or the repository.
2. Run `uv run python -m app.domains.billing.setup` once. It creates the prices.
3. In Stripe:
   - enable **Stripe Tax** with your GST registration;
   - configure the **customer portal** (allow plan changes between the six prices, cancel at period end);
   - add a webhook endpoint for `https://<your API>/api/v1/billing/stripe/webhook` with these events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid` and `invoice.payment_failed`.
4. Add your own organizations' ids to `BILLING_COMPLIMENTARY_ORGANIZATIONS`. Then set `BILLING_ENABLED=true`.

**D. Documents to read:**

- this report;
- `PHASE_13_PROGRESS.md`;
- API_SPECIFICATION §19N;
- DATABASE_SCHEMA §14G;
- `.env.example` (the Billing block).

## 13. Next

1. **Your review** of Phase 13 (§12), and of Phases 8 – 12 if you have not done them yet.
2. **Step 0** for Phases 8 – 13 once the keys and accounts are in place.
3. Then **Phase 14**, as in the roadmap. Its plan comes to you for approval first.
