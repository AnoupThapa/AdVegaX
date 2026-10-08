# Phase 6 — Unified Analytics & Financial Engine

**Status:** Not started · **Depends on:** 2A, 3, 4, 5 (2B recommended) · **Milestone:** M2

## Goal
One trustworthy, source-labelled view of revenue, spend, cost and profit per organization, store, channel, campaign and product.

## Prerequisite decisions (stop condition — PROJECT_RULES §18)
Signed-off metric definitions: net revenue, refunds timing, COGS, shipping cost, payment fees, contribution profit, blended vs platform-reported ROAS, CPA, CAC, attribution model, FX source/date, reporting time zone, rounding.

## Milestones
1. **Linking** — store ↔ ad accounts ↔ GA4 property per organization
2. **FX** — `fx_rates` from an approved source; conversions only in deterministic code
3. **Reporting calendar** — organization reporting time zone; documented handling of differing source time zones
4. **Financial engine v1** — full metric registry, additive `financial_daily` components, ratios computed on read, `null` for zero denominators
5. **Recompute pipeline** — idempotent recalculation of date windows when late data arrives (refunds, restatements, cost edits)
6. **Analytics API** — `/analytics/overview|campaigns|products|financial` with definition version, sources and freshness on every figure
7. **Dashboards** — overview, channel, campaign, product profitability; platform-reported and blended metrics never mixed

## Exit criteria
Golden datasets reproduce hand-calculated results across currencies and time zones; no screen computes its own formula.
