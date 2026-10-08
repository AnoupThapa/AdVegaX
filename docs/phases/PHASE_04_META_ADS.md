# Phase 4 — Advertising: Meta (read-only)

**Status:** Not started · **Depends on:** Phase 1 · **Milestone:** M2

## Goal
Discover Meta ad accounts and sync campaigns, ad sets, ads, creatives and insights into the same normalized advertising models.

## Prerequisites
Meta developer app (development mode), test Business and ad account. Start App Review / Business Verification for read permissions early; write permissions are needed only from Phase 10A.

## Step 0 — Verify
Current Marketing API version and lifecycle; permissions (`ads_read`, later `ads_management`, `business_management`); token strategy (user vs system user) and expiry; insights fields, attribution settings and async report jobs; rate-limit headers; budgets in minor currency units.

## Milestones
1. `MetaAdsProvider`; capabilities; fixture tests
2. Connect flow + token lifecycle (expiry monitoring, reconnect prompts)
3. Ad account discovery and linking
4. Structure sync (campaign → ad set → ad → creative reference); ad set maps to normalized `AdGroup`
5. Insights sync with look-back; async jobs for large ranges
6. Rate limiting per business/app usage headers
7. UI parity with Google Ads views

## Exit criteria
Test account syncs; minor-unit/currency conversions covered by tests; no write calls exist.
