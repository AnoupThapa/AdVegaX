# Phase 13 — Stripe Billing & Entitlements

**Status:** Not started · **Depends on:** Phase 1 entitlement stub; can run in parallel after Phase 6 · **Milestone:** M6

## Prerequisite decisions
Plans, prices, trial, usage limits (incl. AI usage), tax handling; Shopify billing implications for Shopify-sourced merchants (DISCOVERY_REPORT C1).

## Milestones
1. Billing provider interface; Stripe implementation (test mode)
2. Plans/entitlements/usage tables; entitlement enforcement replaces stub
3. Checkout, customer portal, plan change, cancel
4. Signature-verified, idempotent webhooks; nightly reconciliation
5. Owner-only billing UI; billing events audited

## Exit criteria
Webhook duplicate/out-of-order tests pass; entitlements enforced server-side.
