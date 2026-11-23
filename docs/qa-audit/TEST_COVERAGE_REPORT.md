# Test coverage report

## Suites run during this audit

| Suite                                                               | Command                                              | Result                                                                                                                                                          | Coverage                                     |
| ------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Backend unit, API, security, migration and worker tests (125 files) | `uv run pytest --cov=app --cov-branch`               | **2,127 passed, 2 errors.** The errors were caused by the auditor stopping Redis mid-run; the affected file was rerun and passed 18/18. Time: 36 min on 2 CPUs. | **95.30%** line+branch (gate 85%)            |
| Security-critical modules gate                                      | `coverage report --fail-under=95 --include=…`        | Pass                                                                                                                                                            | **98%**                                      |
| Backend lint and types                                              | `ruff check`, `ruff format --check`, `mypy --strict` | Clean (263 files)                                                                                                                                               | —                                            |
| Backend dependencies                                                | `pip-audit --strict`                                 | **Fail:** certifi advisory (QA-004)                                                                                                                             | —                                            |
| Frontend lint, format, types, API-type drift, unit tests            | `npm run check`                                      | **649 passed**                                                                                                                                                  | 96.11% lines, **85.83% branches** (gate 85%) |
| Frontend production dependencies                                    | `npm audit --omit=dev --audit-level=high`            | 0 vulnerabilities                                                                                                                                               | —                                            |
| End-to-end with axe                                                 | `npx playwright test` (21 journeys)                  | 20 passed, 1 flaky (QA-010)                                                                                                                                     | —                                            |

## What kinds of tests exist

| Type                      | Present                                                                                                                     | Notes                                                                                                           |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Unit                      | Yes                                                                                                                         | Rules for actions, autopilot, billing, strategy budgets, creative policy, encryption, settings, funnel findings |
| Integration and API       | Yes                                                                                                                         | About 75 API test files against real PostgreSQL and Redis                                                       |
| Database                  | Yes                                                                                                                         | Migrations up, down and up; models match migrations; RLS forced on every tenant table; least-privilege roles    |
| Authentication            | Yes                                                                                                                         | `test_auth.py`, throttling, sessions, password reset, CSRF                                                      |
| Authorization and tenancy | Yes                                                                                                                         | A route sweep for non-members, foreign child ids, RLS behaviour, composite keys                                 |
| End-to-end                | Yes                                                                                                                         | 21 journeys including keyboard-only and tenant boundary                                                         |
| Regression ("golden")     | Yes                                                                                                                         | `test_metrics_golden.py`, `test_funnel_golden.py`                                                               |
| Security                  | Yes                                                                                                                         | SSRF, headers and CSP, credentials, static rules (`tests/security/*`)                                           |
| Accessibility             | Yes                                                                                                                         | axe in every e2e journey; design-token rules as a static test                                                   |
| Performance               | **No automated tests.** There is a k6 script, never run in CI or against a deployed stack, and Lighthouse runs were manual. |                                                                                                                 |

## Quality of the tests

- The assertions check outcomes rather than calls: persisted rows, status codes, audit entries, and figures shown in the UI.
- Negative cases are common: validation, 404 for foreign ids, CSRF failures, throttles, refused unsafe configuration.
- External platforms are simulated at the HTTP level (`*_sim.py`), not mocked at the function level. This keeps the real client code under test. The cost is that only behaviour the simulator knows about is tested (QA-002).
- Each test gets isolated databases. The suite tolerates no shared state, except Redis db 15, which is flushed per test.

## Gaps in critical areas (lowest-covered backend modules)

| Module                               | Coverage | Why it matters                          |
| ------------------------------------ | -------: | --------------------------------------- |
| `app/workers/job_tasks.py`           |      69% | Scheduled tasks (sync, purge, recovery) |
| `app/domains/builder/launch.py`      |  **72%** | Creates real campaigns on ad platforms  |
| `app/domains/actions/engine.py`      |  **79%** | Sends approved changes to ad platforms  |
| `app/domains/platform/store.py`      |      81% | Encrypted Admin-portal keys             |
| `app/providers/google_ads/writes.py` |      83% | Google Ads write calls                  |
| `app/domains/autopilot/runner.py`    |      86% | Changes without a person in the loop    |
| `app/providers/meta_ads/writes.py`   |      87% | Meta write calls                        |

The code that spends customers' money has lower coverage than the average (QA-019).

**Frontend:** the lowest branch coverage is in the account security page (50%), `AccountMenu` (58%), the strategy detail page (64%) and several label maps.

## Missing tests

- Concurrency on create endpoints. QA-005 was found by hand.
- The Admin two-step code throttle (it does not exist, QA-003).
- Database-outage responses (QA-008).
- Correlation ids on 500 responses (QA-007).
- Load and soak tests.
- Tests against real platform sandboxes.
- Visual regression.
