# Phase 4 — Task Reports

Plan: `PHASE_04_PLAN.md` (approved 2026-10-18, A22, all recommendations). One report per task; `PHASE_04_REPORT.md` follows task 4-08.

| Task | Status |
|---|---|
| 4-01 Step 0 on the sandbox and one real account | ⏸ Waiting — needs the Meta app, a sandbox ad account and network access to Meta's API (Q-4-10, option C) |
| 4-02 Meta sign-in, Graph client, simulator, read-only guard | ✅ Done — awaiting review |
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

---

## 4-02 — Meta sign-in, Graph client, simulator and read-only guard (2026-10-18)

**Completed**
- **"Connect Meta" works end to end** (against the simulator):
  - the person is sent to Meta's own login page with AdVegaX's **Login for Business configuration**, which asks for read-only ads access (`ads_read`) and business details, with PKCE and a single-use state;
  - back at AdVegaX, the code is exchanged **on the server** for a token, then for the **long-lived token** (about 60 days); its end date is stored, encrypted with the token;
  - AdVegaX checks who signed in and which permissions they granted. If ads access was unticked, the connection is refused with a plain message;
  - declining on Meta's page connects nothing; a code Meta refuses connects nothing;
  - reconnecting with the same Facebook account reuses the connection; another Facebook account is a second connection; the same Facebook account may also serve another organization (Q-4-11);
  - disconnect asks Meta to remove AdVegaX's permission and always deletes our copy, even when Meta cannot be reached.
- **Secrets never travel in an address.**
  - The token goes in the `Authorization` header; the app secret only in the body of the token exchange.
  - Every call carries `appsecret_proof`, so a stolen token alone cannot be used against AdVegaX's app.
- **A Graph client** that:
  - follows Meta's paging cursor (never Meta's `next` link, which repeats the token);
  - turns Meta's error codes into plain codes (sign-in rejected, permission missing, rate limited with Meta's own wait time, too much data, no access);
  - reads Meta's usage headers on every answer, for pacing in 4-06.
- **Read-only guard:**
  - every request goes through one gate that allows reading, plus three documented calls that change nothing in an ad account (the token exchange, starting a report, removing AdVegaX's own permission);
  - anything else, such as creating a campaign, is refused before it is sent;
  - static tests check that the gate is the only way out and that `ads_management` is never requested.
- **A Meta simulator** for tests, which refuses tokens in addresses, wrong proofs and expired tokens.
- **Problem found and fixed while testing:** the plan's token check (`debug_token`) puts the token in the web address, and the HTTP library's request log would have recorded it. The person and permissions now come from `/me` and `/me/permissions`, with the token in the header. The test scans that log too.

**Files changed** (13)
- New (6): `app/providers/meta_ads/{__init__,client,provider}.py`, `tests/meta_sim.py`, `tests/providers/test_meta_ads_client.py` (79 tests), `tests/api/test_meta_ads_connect.py` (17 tests).
- Modified (7): `app/core/settings.py` (`META_ADS_ENABLED`, `META_APP_ID`, `META_APP_SECRET`, `META_LOGIN_CONFIG_ID`, `META_API_VERSION`), `app/providers/base/registry.py`, `tests/security/test_static_rules.py` (2 new rules), `.env.example` (Google Ads and Meta entries), docs `INTEGRATION_GUIDES.md`, `SECURITY.md`, this report.
- Deleted: none. No migration.

**Tests**
- **100 new.**
- **Backend `make check`: 1,162 passed**, coverage 97 % (Meta provider 98–99 %).
- **Frontend `npm run check`: 358 passed** (unchanged).

**Security**
- Read-only gate plus static tests.
- Tokens are encrypted, with their end date. No secret is ever placed in a URL; the tests scan responses, the audit log and the logs, including the HTTP request log.
- No Facebook name, email or picture is requested or stored.

**Deviations**
1. **No `debug_token`.** `/me` and `/me/permissions` are used instead (see above). `appsecret_proof` makes Meta itself confirm the token belongs to AdVegaX's app.
2. **The token exchange is a POST with the secret in the body.** Meta documents it as a GET with the secret in the address; to confirm in Step 0 that Meta accepts the POST form.
3. **The provider code is `meta_ads`** (the Phase 3 static test listed `meta`; updated).

**Blocked:** Step 0 (4-01): needs the Meta app, a sandbox ad account and network access to Meta.

**Next task:** 4-03 — discovery:
- the person's ad accounts, grouped by the business that owns them;
- status, currency and time zone;
- which accounts cannot be linked, and why.

