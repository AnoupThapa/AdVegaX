# Phase 18 — Fixing the quality audit's code findings

The scope was approved on 2026-11-13: all 15 code findings from `docs/qa-audit/MASTER_DEFECT_REGISTER.md`, plus a local load test. QA-001, QA-002 and QA-006 were left out because they need hosting, accounts or a performance project. Security probing was not approved, and none was done.

## What changed

| ID     | Fix                                                                                                                                                                                                                                                     | Where                                                                                       | Proof                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| QA-003 | Each Admin two-step code attempt counts, whether right or wrong: 5 per person and 20 per address per 15 minutes. After that, even the right code is refused until the window passes. Wrong codes are written to the audit log (`platform.code_failed`). | `platform/service.py` `_check_code`; settings `THROTTLE_ADMIN_CODE_PER_*`                   | `test_two_step_codes_cannot_be_guessed_or_reused`                                                                                                  |
| QA-013 | A code's time step is remembered once it is accepted (Redis `SET NX`), so the same code cannot be used twice                                                                                                                                            | `platform/totp.py` `match`, `service.py`                                                    | `test_two_step_sign_in` (a reused code gives 422)                                                                                                  |
| QA-004 | certifi upgraded to 2026.10.23; `pip-audit --strict` now reports no known vulnerabilities                                                                                                                                                               | `backend/uv.lock`                                                                           | pip-audit                                                                                                                                          |
| QA-005 | A lost race on a unique rule now answers **409 CONFLICT** instead of a server error. Other broken database rules stay 500s, because they are bugs.                                                                                                      | `core/errors.py`                                                                            | `test_database_errors_become_conflict_or_unavailable`. Live probe: 5 identical invitations at once gave 201 + 4 × 409, with one invitation stored. |
| QA-008 | A database that cannot be reached answers **503 SERVICE_UNAVAILABLE**                                                                                                                                                                                   | `core/errors.py`                                                                            | Same test. Live test: PostgreSQL stopped gave 503; it recovered on restart.                                                                        |
| QA-007 | Unexpected errors are answered inside the request-id middleware, so the response and the log both carry the id                                                                                                                                          | `core/correlation.py`, `core/errors.py` `unhandled_response`                                | `test_unhandled_exception_returns_generic_500`. Live: no `"correlation_id": null` in the API log.                                                  |
| QA-009 | The reporting currency must be an ISO 4217 code: the same 162-code list the web form offers                                                                                                                                                             | `core/currencies.py`, `organizations/schemas.py`                                            | `test_organization_validation` (`ZZZ` gives 422)                                                                                                   |
| QA-010 | Playwright runs with reduced motion, and the Overview and landing entrance animations move text without fading it                                                                                                                                       | `playwright.config.ts`, `dashboard.module.css`, `overview.module.css`, `landing.module.css` | Full e2e: 21/21                                                                                                                                    |
| QA-011 | The Admin organization and people lists are searched, filtered, sorted and paged on the server, 50 per page, with no hidden cap. The portal's counts come from the health endpoint. The portal shows "Showing 1–50 of N" with Previous and Next.        | `platform/service.py`, `platform/router.py` (`ListEnvelope`), `features/admin/*`            | `test_admin_lists_are_paged_and_searched_in_the_database`; web test "searches, filters, sorts and pages on the server"                             |
| QA-012 | Request bodies are read chunk by chunk and abandoned past the limit, so a chunked upload is never held in memory whole                                                                                                                                  | `core/security/middleware.py` `_read_at_most`                                               | `test_body_size_and_content_type` (chunked 1 MiB+ gives 413)                                                                                       |
| QA-014 | "How is this calculated?" disclosures are now 26 px tall, and the Creatives file picker 44 px                                                                                                                                                           | `overview.module.css`, `creatives.module.css`                                               | Design-token test                                                                                                                                  |
| QA-015 | When the API cannot be reached, the app retries once after 0.5 s, then shows the message. Server errors still retry twice, after 0.5 s and 1 s.                                                                                                         | `lib/query/query-client.ts`                                                                 | `query-client.test.tsx`                                                                                                                            |
| QA-016 | Documented why `user_action_tokens` has no RLS                                                                                                                                                                                                          | `docs/DATABASE_SCHEMA.md`                                                                   | —                                                                                                                                                  |
| QA-017 | Migration **0028** adds indexes for the 7 foreign keys no index started with (cascades from organizations, ad accounts, products, orders)                                                                                                               | `alembic/versions/0028_foreign_key_indexes.py`, models                                      | Migration round-trip and models-match tests                                                                                                        |
| QA-018 | "Suspend <organization>" asks first and says what happens. Reactivating does not ask.                                                                                                                                                                   | `features/admin/AdminPage.tsx` (`ConfirmDialog`)                                            | Web tests (Cancel sends nothing; Suspend sends once)                                                                                               |
| QA-019 | 11 new failure-path tests for the code that changes live campaigns                                                                                                                                                                                      | `tests/api/test_action_engine_failures.py`, `tests/api/test_builder_failures.py`            | See below                                                                                                                                          |

### QA-019: what the new tests prove

- A crash while sending a change, or while creating a campaign, is recorded as **unknown** and looked up later. It is never marked "failed" and never sent again blind.
- A platform switched off after approval fails the change **before** anything is sent.
- A campaign that cannot be read before sending is retried with back-off, then failed with "not sent". Nothing is created.
- Cancelled and paused changes are not sent. A draft that changed while queued goes "stale".
- The sweep looks up "unknown" changes again only until the look-up limit.

Coverage, measured with the change, builder, Autopilot and recommendation test files:

| Module                 | Before | After  |
| ---------------------- | ------ | ------ |
| `actions/engine.py`    | 79%    | 85%    |
| `builder/launch.py`    | 72%    | 81%    |
| `google_ads/writes.py` | 83%    | 80–83% |
| `meta_ads/writes.py`   | 87%    | 83–87% |

The writes modules show a range because those tests alone cover less than the full suite does. QA-019 stays **Improved**, not Fixed. The rest of the gap is in provider write paths (removing draft objects, Meta step failures), which need richer simulator scenarios.

## Checks run

| Check                                                         | Result                                                                                                              |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Backend: full suite with coverage                             | **2,131 passed**, 95.31% (gate 85%); security-critical gate pass. The 11 new failure tests passed in their own run. |
| Backend: ruff, format, mypy `--strict` (264 files), pip-audit | Clean; no known vulnerabilities                                                                                     |
| Frontend: `npm run check`                                     | **650 passed**; 96.21% lines, 85.89% branches; 0 production vulnerabilities                                         |
| End-to-end (Playwright + axe), production build               | **21/21 passed**                                                                                                    |
| Live probes (local)                                           | Currency `ZZZ` gives 422; concurrent invitations give 409s; database down gives 503 with a request id               |

## Load test (local only; k6 could not be installed, so a Python equivalent of `scripts/load/advegax.js` was used)

Each simulated person used one signed-in session and browsed the Overview's API calls with 1–3 s pauses, for 60 s per level. Everything ran on one 2-CPU machine: one API process, PostgreSQL, Redis, the worker, the web app and the load generator.

| People | Requests | Req/s |    p50 |          p95 |      Max | Errors |
| -----: | -------: | ----: | -----: | -----------: | -------: | -----: |
|     10 |      301 |   4.8 |  26 ms |        73 ms |   272 ms |      0 |
|     50 |    1,476 |  23.5 |  35 ms |       354 ms |   536 ms |      0 |
|    100 |    2,220 |  35.2 | 318 ms | **2,874 ms** | 4,595 ms |      0 |

- Up to 50 people meets the plan's p95 < 500 ms target. At 100 people the single process saturates at about 35 requests per second. No requests failed, but latency rises sharply, and the funnel is the slowest endpoint.
- This is recorded as **QA-020 (P2)**. Each Fly.io API machine runs one `uvicorn` process, so before launch: size workers to the machine and run the real k6 test on staging.

## Still open

- QA-001: deploy, drills, penetration test, monitoring.
- QA-002: real platform sandboxes.
- QA-006: signed-in page speed on phones.
- QA-020: capacity.
- QA-019: remaining provider write-path tests.
