# AdVegaX — AI Context

Read this first. Then `PROJECT_STATUS.md`, then the current phase plan, then only the documents and code the task needs.

## Project
AdVegaX — independent, multi-tenant e-commerce advertising and growth SaaS.

## Current state (2026-10-08)
| Phase | Status |
|---|---|
| 0 | Complete |
| 1A — Platform core & identity | Implemented, pushed — awaiting review |
| 1B — Integration foundation | Implemented, pushed — awaiting review |
| 1C — Frontend shell | **Approved (A17) — in progress**: 1C-01 to 1C-03 done; next 1C-04 (`phases/PHASE_01C_PROGRESS.md`) |
| 2A onward | Not started |

Repository: https://github.com/AnoupThapa/AdVegaX · working branch `feature/phase-1a`.

## Rules
- Do not implement outside the current, approved phase or task.
- Do not change architecture without product-owner approval.
- Do not invent APIs; the generated OpenAPI schema and `API_SPECIFICATION.md` are the contract.
- Never expose secrets, credentials or platform tokens (responses, logs, audit, errors, UI, AI context).
- Preserve tenant isolation (RLS, composite keys, 404 for non-members).
- Never show unavailable data as 0.
- Run tests, lint and type checks after every change.
- Report every deviation; never delete specs, ADRs, security docs, migrations, tests or config (A1).

## Context hierarchy
`AI_CONTEXT.md` → `PROJECT_STATUS.md` → current phase plan → relevant ARCHITECTURE / DATABASE_SCHEMA / API_SPECIFICATION / SECURITY / PROJECT_RULES sections → relevant source code → tests.

Read the minimum needed. Do not repeat project history or re-explain the architecture; summarize only the constraints relevant to the task.

## Workflow
Product owner (approves) → Claude (implements one task) → tests / CI → independent AI review (security / architecture) → product owner (approve / reject) → Claude (fixes approved issues).

Per task: read task → identify files → inspect existing code → plan minimal change → implement → test → report → **stop**.

## Task prompt template
```text
PHASE   <phase>
TASK    <id> — <name>
CONTEXT Read: AI_CONTEXT.md, PROJECT_STATUS.md, <phase plan>, <specific docs>
SCOPE   <what to build>
DO NOT  <exclusions>
STOP    after <task> is complete and tested
```

## Report template
```text
IMPLEMENTATION REPORT
Completed:     - …
Files changed: - …
Tests:         - X passed · Coverage X %
Security:      - …
Migration:     - … / none
Deviations:    - None / …
Blocked:       - None / …
Next task:     - …
```

## Commands
- Backend checks: `make check` (ruff, mypy --strict, pytest with coverage gates; needs PostgreSQL 16 + Redis 7).
- Frontend checks: `make frontend-check` (Node.js 24; ESLint, Prettier, strict TypeScript, Vitest with coverage, production audit, build).
