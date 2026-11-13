# Functional test report

Environment: local copy of `409ac5a` with PostgreSQL 16, Redis, Mailpit, the API, a Celery worker and the production web build (`next build` + standalone server). It ran the CI feature flags, with all platforms simulated. The demo data (`demo/seed.py`) was used for the manual checks.

## 1. End-to-end journeys (Playwright with axe; real browser, API, database and worker)

| #     | Journey                                                                                                | Result                                                                                              |
| ----- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| 1     | Google Ads accounts are imported and shown with their figures                                          | Pass                                                                                                |
| 2     | A client gives an agency access, the agency works in it, and access ends                               | Pass                                                                                                |
| 3     | Autopilot acts within limits, is shown everywhere and stops at once                                    | **Flaky.** It failed once on an axe contrast reading taken mid-animation, then passed 2/2 (QA-010). |
| 4     | Billing shows the trial, the plan after Checkout and the limits                                        | Pass                                                                                                |
| 5     | A campaign is built paused and goes live only after approval                                           | Pass                                                                                                |
| 6     | Changes to ad accounts are checked, approved, verified and shown                                       | Pass                                                                                                |
| 7     | A GA4 property is imported and shown honestly                                                          | Pass                                                                                                |
| 8     | The full journey works for an owner and an invited member                                              | Pass                                                                                                |
| 9     | The core flows work with the keyboard alone                                                            | Pass                                                                                                |
| 10    | A Meta ad account is imported and shown in Meta's words                                                | Pass                                                                                                |
| 11    | A forgotten password can be reset once from the emailed link                                           | Pass                                                                                                |
| 12    | Recommendations are explained, approved into Changes or rejected                                       | Pass                                                                                                |
| 13–15 | Nonce-based security policy and headers; CSRF token only in memory; unsafe return address ignored      | Pass                                                                                                |
| 16    | Sign out another device, then every device                                                             | Pass                                                                                                |
| 17    | An imported store's revenue and products are shown with availability                                   | Pass                                                                                                |
| 18–19 | An outsider cannot open another organization's pages; a signed-out visitor is sent to sign in and back | Pass                                                                                                |
| 20    | Sales, ad spend and profit are shown together, honestly                                                | Pass                                                                                                |
| 21    | A WooCommerce store connects, imports and explains what needs attention                                | Pass                                                                                                |

The first run took 5.6 minutes: 20 passed, 1 failed.

## 2. API behaviour probes (run by the auditor)

| Feature       | Scenario                                       | Expected                                 | Actual                                                | Status            |
| ------------- | ---------------------------------------------- | ---------------------------------------- | ----------------------------------------------------- | ----------------- |
| Sign-in       | Wrong password                                 | 401                                      | 401 INVALID_CREDENTIALS                               | Pass              |
| Sign-in       | Unknown email                                  | Same answer as a wrong password          | 401 INVALID_CREDENTIALS                               | Pass              |
| Sign-in       | Missing field                                  | 422                                      | 422 VALIDATION_ERROR                                  | Pass              |
| Any write     | Malformed JSON                                 | 400/422                                  | 422                                                   | Pass              |
| Any write     | Form-encoded body                              | 415                                      | 415 UNSUPPORTED_MEDIA_TYPE                            | Pass              |
| Any write     | 1.1 MB body (limit 1 MiB)                      | 413                                      | 413 PAYLOAD_TOO_LARGE                                 | Pass              |
| Organizations | Empty name                                     | 422                                      | 422                                                   | Pass              |
| Organizations | Currency `ZZZ`                                 | 422                                      | **201**                                               | **Fail (QA-009)** |
| Organizations | Time zone `Mars/Base`                          | 422                                      | 422                                                   | Pass              |
| Organizations | Unexpected field `is_admin`                    | Refused or ignored                       | 422                                                   | Pass              |
| Organizations | Unknown organization id                        | 403/404                                  | 404                                                   | Pass              |
| Organizations | Malformed id                                   | 422                                      | 422                                                   | Pass              |
| Stores        | Unknown store in own organization              | 404                                      | 404                                                   | Pass              |
| Invitations   | Role `god`                                     | 422                                      | 422                                                   | Pass              |
| Invitations   | Same email twice, one after the other          | One pending invitation                   | The earlier one is revoked and the new one is pending | Pass              |
| Invitations   | Same email, 5 requests at once                 | One pending invitation, no server errors | One pending invitation, but **4 × 500**               | **Fail (QA-005)** |
| CSRF          | Write without Origin or token                  | 403                                      | 403 CSRF_FAILED                                       | Pass              |
| CSRF          | Write from a foreign Origin with a valid token | 403                                      | 403 CSRF_FAILED                                       | Pass              |
| Sessions      | Sign out                                       | 200                                      | 200                                                   | Pass              |
| Sessions      | Reuse the old cookie after sign-out            | 401                                      | 401                                                   | Pass              |
| Sessions      | No cookie                                      | 401                                      | 401                                                   | Pass              |

## 3. Failure and recovery (controlled, local only)

| Failure                                | Expected                                                          | Actual                                                                                                                                         | Status                            |
| -------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| Redis stopped                          | Readiness 503; sign-in refused safely (the throttle fails closed) | `/health/ready` 503; login 503 SERVICE_UNAVAILABLE. Recovered on restart with no API restart.                                                  | Pass                              |
| Worker stopped, then "forgot password" | Request accepted; email held and sent once on recovery            | 202. The outbox row stayed `pending` (0 attempts) with no email; after the restart it became `sent` (1 attempt) and exactly one email arrived. | Pass                              |
| PostgreSQL stopped                     | Readiness 503; requests fail safely with a clear code             | Readiness 503. `GET /organizations` gave **500 INTERNAL_ERROR with request_id null**. Recovered by itself on the first call after the restart. | Partial (QA-007, QA-008)          |
| API stopped, sign-in in the browser    | A clear message                                                   | "We could not reach AdVegaX. Check your connection and try again."                                                                             | Pass                              |
| API stopped, signed-in page            | A clear message                                                   | "Loading…" for up to about 20 s, then the same message                                                                                         | Pass, with a minor issue (QA-015) |

## 4. Coverage of the brief's scenario list

| Scenario                                                   | How it is covered                                                                                                              |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Normal operation, invalid input, missing input, boundaries | Backend API tests (about 75 files), the probes above and the e2e journeys                                                      |
| Duplicate submissions                                      | Unique constraints (109) and idempotency keys on changes; QA-005 found the one 500                                             |
| Concurrent submissions                                     | Probed for invitations only. Not verified for the other create endpoints.                                                      |
| Network interruption, server failure, database failure     | Section 3                                                                                                                      |
| Unauthorized access, expired sessions                      | `test_route_guards` (every protected route needs a session and CSRF), `test_tenant_isolation`, the session probes              |
| Browser back/forward, refresh                              | Covered indirectly by the e2e journeys. Not separately verified.                                                               |
| Search, sort, filter, pagination                           | Unit tests for the DataTable, admin filters and changes filter. Server-side pagination is missing in the admin lists (QA-011). |

## 5. Not verified

- Live platform behaviour, because only simulators were available (QA-002).
- Concurrency on endpoints other than invitations.
- Browsers other than Chromium.
