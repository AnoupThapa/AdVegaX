# Phase 5 — Progress (Google Analytics 4, read-only)

Plan: `PHASE_05_PLAN.md` (approved 2026-10-19, A23, all recommendations; Q11 settled). One report per task; `PHASE_05_REPORT.md` follows task 5-09.

| Task | Status |
|---|---|
| 5-01 Step 0 on the demo property and one of your properties | ⏸ Waiting — needs the Google OAuth client (with the Analytics APIs enabled) and network access to Google's Analytics APIs (Q-5-9, option C) |
| 5-02 Analytics model, interface, read-only rule | Not started |
| 5-03 Google Analytics sign-in, client, simulator | Not started |
| 5-04 Discovery and linking rules | Not started |
| 5-05 Daily import | Not started |
| 5-06 Ongoing sync, quota pacing, health | Not started |
| 5-07 Read API | Not started |
| 5-08 Web app | Not started |
| 5-09 Journey test, browser test, docs, report | Not started |

## 5-01 — Step 0 on the demo property and one of your properties

Waiting. It needs:
- in the existing Google Cloud project: the Google Analytics Data API and Admin API enabled, and `analytics.readonly` on the consent screen;
- a Google account with Viewer access to one of your GA4 properties (and, optionally, Google's demo account);
- network access to `analyticsdata.googleapis.com`, `analyticsadmin.googleapis.com`, `oauth2.googleapis.com` and `accounts.google.com`.

The rest of Phase 5 is built against Google's documentation and a GA4 simulator meanwhile.
