# Code quality audit

## Overall

The code is maintainable. Another experienced developer could pick it up, helped by consistent domain folders (`models`, `schemas`, `service`, `router`, `rules`), strict typing on both sides, docstrings that cite the requirement they implement, and detailed phase documents.

## Evidence

| Check                                       | Result                                                                                                                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Type safety                                 | `mypy --strict` is clean on 263 files. TypeScript is strict, and API types are generated from OpenAPI, with a drift test on both sides.                                                                 |
| Lint and format                             | ruff, ESLint and Prettier are all clean                                                                                                                                                                 |
| TODO/FIXME/HACK in application code         | **None**                                                                                                                                                                                                |
| Silent exception handling                   | None found. Every `except Exception` site logs the error, and record an "unknown" outcome where a platform's answer is uncertain (`actions/engine.py:320`, `builder/launch.py:252`). No `except: pass`. |
| Fake success or placeholder implementations | None found in production paths. Simulators live only in `backend/tests` and are excluded from the Docker image. The demo seed refuses deployed environments (`demo/seed.py`, tested).                   |
| Hard-coded secrets                          | None. Only development values in `.env.example`, and deployed environments refuse them.                                                                                                                 |
| Design-system drift                         | Prevented by `tests/static/design-tokens.test.ts`                                                                                                                                                       |
| Duplication                                 | Low. Shared helpers for envelopes, errors, tenancy and pagination. Providers repeat a similar shape on purpose, one module per platform.                                                                |

## Concerns

| Item                             | Severity | Notes                                                                                                                                                                                                                                                                                |
| -------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Large modules                    | P4       | `commerce/importer.py` (1,331 lines), `advertising/importer.py` (1,068), `integrations/service.py` (1,008), `analytics/importer.py` (902), `actions/service.py` (876). They are cohesive, but long enough to slow review. Split them by provider or step when they are next changed. |
| String-built interval SQL        | P4       | Three places (`jobs/service.py`, `notifications/delivery.py`) use integer-cast internal values. They are safe, but bound parameters would be cleaner.                                                                                                                                |
| Two layout styles in the web app | P4       | The newer ruled layout (Overview, Admin) sits beside older panels (Reports, Settings). See the UI audit.                                                                                                                                                                             |
| Error-mapping gaps               | P3       | Database outages and integrity races reach the generic 500 handler (QA-005, QA-008), and that handler loses the correlation id (QA-007).                                                                                                                                             |
| `settings.py` size               | P4       | 632 lines with many feature switches; it is well validated. A per-domain settings split would help as the number of switches grows.                                                                                                                                                  |

No refactoring is recommended merely for style.
