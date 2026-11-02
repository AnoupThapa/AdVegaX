# Phase 2A — Commerce: Shopify (read-only) + Finance Core

**Status:** Plan drafted — `PHASE_02A_PLAN.md` (awaiting approval) · **Depends on:** Phase 1 · **Milestone:** M2

## Goal
Connect Shopify stores to an AdVegaX organization and import catalogue, inventory, orders and refunds into normalized models, with the first deterministic store-level financial metrics.

## Prerequisite decisions
- Shopify distribution approach (DISCOVERY_REPORT §3 C1); written answer from Shopify Partner Support on billing/listing for an externally billed SaaS
- Financial definitions v1 for store metrics (gross/net revenue, discounts, refunds timing, COGS source, missing-cost behaviour)
- Customer PII policy (recommended: hashed customer key only)
- Backfill depth; whether the same store may be connected to two organizations
- Development credentials: Shopify Partner account + development store (no production credentials needed)

## Step 0 — Verify (before any code)
Current Shopify GraphQL Admin API version and support window; minimum scopes; protected customer data requirements; `read_all_orders` need; install/OAuth flow for public apps; **expiring offline tokens** (1 h access / 90-day rotating refresh; no concurrent acquire+refresh); mandatory privacy webhooks; webhook HMAC verification; bulk operations; cost field; rate limits. Record results in `docs/INTEGRATION_GUIDES.md` (Shopify section) with date.

## Milestones
1. **Connector skeleton** — `ShopifyProvider` implementing `CommerceProvider`; capability declaration; recorded-fixture contract tests
2. **Connect flow** — "Connect Shopify" from AdVegaX → Shopify install/authorization → callback bound to server-side state → store linked to the organization; reauthorize; disconnect
3. **Token lifecycle** — encrypted storage; background refresh with per-store distributed lock; revocation and failure states surfaced to UI
4. **Webhooks** — registration, HMAC verification, `webhook_events` dedupe, async processing, uninstall handling, privacy webhooks (`customers/data_request`, `customers/redact`, `shop/redact`)
5. **Initial import** — products, variants, inventory, orders, order lines, refunds, costs via bulk operations; `sync_runs` tracking
6. **Incremental sync + reconciliation** — webhooks plus scheduled reconciliation (webhooks are not guaranteed)
7. **Finance core** — Decimal functions for store-only metrics; metric-definition registry v1; `product_cost_history`; golden-file tests
8. **UI** — connection status, products list/detail, basic store revenue view

## Data (proposed, migrations planned during the phase)
stores, products, product_variants, inventory levels, orders, order_items, refunds, refund_lines, customer_refs (hashed), product_cost_history, webhook_events, sync_runs, oauth_states

## Tests
Wrong-tenant tests on all new routes; webhook duplicate/out-of-order tests; token refresh race test; finance golden tests; provider contract tests (no live calls in CI).

## Exit criteria
A development store connects, imports, stays in sync, disconnects and reauthorizes cleanly; finance figures match hand-calculated fixtures; no PII beyond the approved policy stored.
