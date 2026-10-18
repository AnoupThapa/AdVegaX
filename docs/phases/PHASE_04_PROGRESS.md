# Phase 4 — Task Reports

Plan: `PHASE_04_PLAN.md` (approved 2026-10-18, A22, all recommendations). One report per task; `PHASE_04_REPORT.md` follows task 4-08.

| Task | Status |
|---|---|
| 4-01 Step 0 on the sandbox and one real account | ⏸ Waiting — needs the Meta app, a sandbox ad account and network access to Meta's API (Q-4-10, option C) |
| 4-02 Meta sign-in, Graph client, simulator, read-only guard | Not started |
| 4-03 Discovery and linking rules | Not started |
| 4-04 Structure import | Not started |
| 4-05 Insights import | Not started |
| 4-06 Ongoing sync, rate limits, token expiry | Not started |
| 4-07 API additions and web app | Not started |
| 4-08 Journey test, browser test, docs, report | Not started |

---

## 4-01 — Step 0 on the sandbox and one real account

Waiting. Step 0 needs:
- the AdVegaX Meta business portfolio and developer app (Marketing API and Facebook Login for Business, with a configuration asking for `ads_read` and `business_management`);
- a sandbox ad account, and one real ad account for the figures comparison;
- the app ID and app secret in the local untracked settings file;
- network access to `graph.facebook.com` and `www.facebook.com`.

Until then, work follows option C: build against Meta's documentation and a simulator. Everything Step 0 would confirm is marked "to confirm live".
