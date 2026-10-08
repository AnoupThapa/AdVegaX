# Phase 2B — Commerce: WooCommerce (read-only)

**Status:** Not started · **Depends on:** Phase 2A · **Milestone:** M2

## Goal
Connect self-hosted WooCommerce stores safely and map them into the **same** normalized models and finance core as Shopify — proving the commerce abstraction is platform-independent.

## Prerequisite decisions
- Supported WooCommerce/WordPress minimum versions; HTTPS-only stores (recommended)
- COGS source for WooCommerce (native field if available in supported versions, plugin, or manual entry)
- Development WooCommerce test site (local or hosted)

## Step 0 — Verify
REST API v3 endpoints for products, variations, orders, refunds; `/wc-auth/v1/authorize` key-generation flow and callback payload; webhook signature header/algorithm; native cost-of-goods support and version; pagination; time zone and currency settings; multi-currency plugin behaviour.

## Milestones
1. **Connector** — `WooCommerceProvider`; capability detection at connect time (version, permalinks, webhooks, COGS)
2. **Connect flow** — store URL validation/normalization → key-generation authorize URL with single-use nonce as `user_id` → HTTPS callback receives keys → encrypted storage; `read` scope only
3. **SSRF hardening** — all calls through the Phase 1 SSRF-safe client; DNS/IP checks per request; no query-string credentials
4. **Import & sync** — products/variations/inventory/orders/refunds; polling reconciliation; webhooks where verified
5. **Store health** — reachability, auth failures, revoked keys, version drift shown in UI
6. **Parity tests** — equivalent Shopify and WooCommerce fixtures produce identical normalized orders and finance results

## Key risks
SSRF (CRITICAL), heterogeneous hosting/security plugins, header stripping, non-expiring keys, missing cost data.

## Exit criteria
Test site connects, imports and stays in sync; SSRF suite green; finance parity with Shopify fixtures.
