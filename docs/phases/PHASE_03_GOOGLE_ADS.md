# Phase 3 — Advertising: Google Ads (read-only)

**Status:** Not started · **Depends on:** Phase 1 · **Milestone:** M2

## Goal
Discover Google Ads accounts and sync campaign structure and daily performance into normalized advertising models.

## Prerequisites
Google Cloud project + OAuth client (test); Google Ads developer token (test access is enough for development); manager (MCC) test account. Apply for production access levels early — long lead time.

## Step 0 — Verify
Current API version and sunset date; developer token access levels and limits; OAuth scope and app verification; `login-customer-id` / MCC handling; GAQL resources and metrics for campaign/ad group/ad daily stats; micros; conversion restatement windows; Required Minimum Functionality obligations (relevant from Phase 10B).

## Milestones
1. `GoogleAdsProvider` implementing `AdvertisingProvider`; capabilities; fixture tests
2. OAuth connect (separate grant from GA4), token storage/refresh, disconnect
3. Account discovery incl. manager hierarchy; user selects accounts to link
4. Structure sync: campaigns, ad groups, ads, budgets (typed), status
5. Daily performance sync with rolling look-back re-sync and upsert; `ad_performance_daily` uniqueness
6. Rate limiting/backoff per developer token and account; error classification
7. UI: accounts, campaigns, platform-reported metrics (clearly labelled)

## Exit criteria
Test account syncs reliably; restated data overwrites correctly; no write calls exist in code.
