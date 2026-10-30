# Runbook — Stripe set-up (Phase 13)

1. Test mode first: put `STRIPE_SECRET_KEY` (sk_test_…), then run `uv run python -m app.domains.billing.setup` (creates the six prices; safe to repeat).
2. Webhook endpoint `https://api-staging.<your domain>/api/v1/billing/stripe/webhook` with the events `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`; put its signing secret in `STRIPE_WEBHOOK_SECRET`.
3. `STRIPE_API_VERSION` = the version shown in the Stripe dashboard (required when deployed).
4. Stripe Tax with your GST registration; customer portal: plan changes between the six prices, cancel at period end.
5. Staging refuses live keys (`sk_live_`); production uses live keys only after the go-live checklist.
