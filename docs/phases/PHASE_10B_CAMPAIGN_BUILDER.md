# Phase 10B — Campaign Builder

**Status:** Not started · **Depends on:** 8, 9, 10A · **Milestone:** M4

## Goal
Turn an approved strategy and approved creatives into a validated, platform-specific campaign that launches only on explicit user action.

## Step 0 — Verify
Campaign types and required fields for Google Ads and Meta at current API versions; Google Ads Required Minimum Functionality obligations; Meta special ad categories and current campaign structures.

## Milestones
1. Builder translating normalized campaign drafts to provider configurations (inside providers)
2. `POST /campaigns/validate` (deterministic + provider validate-only)
3. Review screen showing exactly what will be created and the computed budget
4. Launch via Action Engine with `Idempotency-Key`; children built paused; activation last
5. External IDs recorded; first sync scheduled

## Exit criteria
No spend without explicit launch; failed launches leave nothing active.
