# Phase 7 — Funnel Intelligence

**Status:** Not started · **Depends on:** Phase 6 · **Milestone:** M3

## Goal
Show impression → click → landing page view → product view → add to cart → checkout → purchase, with conversion rates, by date, product, campaign and platform where attributable.

## Prerequisite decisions
Approve funnel stage model (DISCOVERY_REPORT C2: refund/cost/profit/repeat purchase as financial metrics, not stages).

## Milestones
1. Stage definitions with **declared source per stage** (ads → impressions/clicks; GA4 → behaviour; commerce → purchases)
2. `funnel_daily` aggregation from normalized data
3. Attribution joins (UTMs/campaign identifiers) with explicit "unattributable" buckets
4. `/funnel` API and UI with source labels and "not available" states
5. Drop-off highlighting (deterministic), ready to feed AI in Phase 11

## Exit criteria
Funnel numbers reconcile to source aggregates; missing stages never shown as zero.
