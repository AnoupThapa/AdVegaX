# Phase 5 — Analytics: GA4 (read-only)

**Status:** Not started · **Depends on:** Phase 1 · **Milestone:** M2

## Goal
Discover GA4 properties and import aggregated behavioural data (sessions, landing pages, ecommerce events) for the funnel.

## Prerequisite decisions
Approve aggregated-only model (`analytics_daily`, no BigQuery export in MVP) and adding the **GA4 Admin API** for property discovery (DISCOVERY_REPORT C6).

## Step 0 — Verify
Admin API account/property listing; Data API dimensions/metrics for ecommerce funnel (`view_item`, `add_to_cart`, `begin_checkout`, `purchase`, landing page, source/medium/campaign); quotas (tokens); thresholding/sampling; data freshness; OAuth scope verification.

## Milestones
1. `GA4Provider` implementing `AnalyticsProvider`; fixtures
2. Google OAuth grant (separate from Ads), property discovery and linking to a store
3. Daily aggregated pulls with look-back; quota-aware scheduling
4. Ecommerce-tagging detection: stages unavailable are marked "not available", never zero
5. UI: property status and traffic overview

## Exit criteria
Test property syncs within quota; tagging detection works for tagged and untagged fixtures.
