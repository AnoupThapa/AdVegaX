# AdVegaX — Project Rules & AI Agent Constitution

These rules apply to every AI coding agent and human contributor.

## 1. Mission

Build a production-grade, commercial, multi-tenant SaaS application. Do not treat this as a prototype once production architecture is established.

## 2. Non-Negotiable Rules

1. Read the relevant specification before changing code.
2. Inspect the existing repository before creating or replacing files.
3. Do not rewrite working systems without evidence.
4. Do not invent APIs, parameters, permissions, SDK behavior or platform features.
5. Verify current official third-party documentation before implementing integrations.
6. Never expose secrets, tokens, passwords or private keys in source, logs, tests or errors.
7. Never bypass authentication or authorization.
8. Never bypass platform restrictions.
9. Never use browser automation when an official supported API exists.
10. LLM output is untrusted input.
11. Validate all AI output against strict schemas.
12. AI cannot directly execute arbitrary code.
13. AI cannot directly perform financial calculations.
14. AI cannot directly execute advertising mutations.
15. All external actions must pass through controlled application services.
16. Every tenant-owned resource requires server-side tenant authorization.
17. Use least privilege.
18. Prefer explicit, readable code over clever abstractions.
19. Add tests for important behavior and every important bug fix.
20. Keep migrations reversible where practical.
21. Do not mix unrelated changes into a feature.
22. Do not silently change product requirements.
23. If requirements conflict, stop and identify the conflict.
24. If an external API is uncertain, stop and verify rather than guess.
25. Never claim completion without running appropriate verification.

## 3. AI Agent Workflow

For every meaningful task:

### Step A — Understand
Read (all specifications live in `docs/`):
- docs/MASTER_SPECIFICATION.md
- docs/PROJECT_RULES.md
- relevant architecture/database/API documents
- relevant source code

### Step B — Inspect
Report:
- current implementation,
- relevant files,
- dependencies,
- risks,
- missing requirements.

### Step C — Plan
Before coding, state:
- proposed changes,
- files to modify,
- migrations,
- tests,
- security implications,
- integration implications.

### Step D — Implement
Make the smallest coherent change.

### Step E — Verify
Run:
- tests,
- lint,
- type checks,
- formatting,
- migration checks,
- integration checks where relevant.

### Step F — Report
State:
- what changed,
- files changed,
- tests run,
- failures,
- known limitations,
- next recommended step.

## 4. Coding Standards

Backend:
- Python type hints.
- Pydantic validation.
- Clear service/domain boundaries.
- Centralized configuration.
- Explicit transaction handling.
- Structured logging.
- No business logic in route handlers where avoidable.

Frontend:
- TypeScript strict mode.
- Typed API clients.
- Reusable components.
- Server/client boundaries used intentionally.
- No secrets in browser code.
- Accessible UI.

## 5. API Rules

Every endpoint must define:
- authentication requirement,
- authorization requirement,
- request validation,
- response schema,
- error behavior,
- tenant boundary,
- idempotency requirements where applicable.

Do not return internal exception traces to users.

## 6. Database Rules

- PostgreSQL is the primary transactional database.
- Use migrations.
- Every foreign key must have an intentional index strategy.
- Add uniqueness constraints for natural identifiers.
- Use timestamps consistently.
- Never delete data casually when audit/history is required.
- Prefer soft deletion where business history matters.
- Avoid N+1 queries.
- Use transactions for multi-step mutations.

## 7. Security Rules

Secrets:
- environment/secret manager only,
- encrypted at rest where persisted,
- never log raw credentials.

OAuth:
- use state/PKCE where supported and appropriate,
- validate callbacks,
- store tokens securely,
- handle revocation/expiration,
- request minimum scopes.

Authorization:
- deny by default,
- centralize permission checks,
- validate tenant/resource ownership.

## 8. AI Rules

Treat every model response as potentially malicious or malformed.

Require:
- JSON schema,
- allowed enum values,
- numeric ranges,
- product/resource existence,
- budget limits,
- policy checks,
- authorization checks.

AI-generated action must contain enough context to explain:
- recommendation,
- reason,
- expected outcome,
- assumptions,
- confidence,
- risks,
- affected resource,
- proposed changes.

## 9. Financial Rules

Financial values must come from deterministic code.

Do not let an LLM decide:
- revenue,
- profit,
- spend,
- ROAS,
- CPA,
- margin,
- currency conversion,
- budget totals.

Use Decimal or an equivalent safe monetary representation.

## 10. External API Rules

Each provider must have a connector/provider boundary.

Do not spread Google/Meta/Shopify-specific code throughout the application.

Connector responsibilities:
- authentication,
- request construction,
- provider response parsing,
- provider errors,
- rate limits,
- retries,
- provider IDs.

Domain services should use internal normalized models.

## 11. Idempotency

Idempotency is required for operations such as:
- campaign creation,
- campaign updates,
- budget changes,
- webhook processing,
- sync jobs,
- billing webhook processing.

Do not create duplicate external resources because a request was retried.

## 12. Background Jobs

Jobs must support:
- retry policy,
- exponential backoff,
- dead-letter/failure handling,
- idempotency,
- observability,
- correlation IDs.

Long-running provider calls must not block ordinary HTTP requests.

## 13. Logging

Logs should contain:
- timestamp,
- level,
- service/module,
- request/correlation ID,
- organization ID when safe,
- user ID when safe,
- event/action,
- outcome,
- duration.

Never log:
- access tokens,
- refresh tokens,
- passwords,
- API keys,
- sensitive payment data.

## 14. Testing

At minimum:
- unit tests for domain logic,
- integration tests for DB behavior,
- API tests,
- authorization tests,
- tenant isolation tests,
- provider adapter tests,
- financial calculation tests,
- AI schema tests,
- regression tests.

## 15. Git Rules

Use:
- feature branches,
- focused commits,
- pull requests,
- automated checks.

Do not push directly to production.

Do not allow two AI agents to edit the same repository concurrently.

Recommended workflow:
Primary agent → commit → independent review → fix → test → merge.

## 16. Change Safety

### 16.1 File deletion (Phase 0 approval A1)
Deletion is permitted only when necessary for the approved architecture, and must be conservative:
1. Check whether the file is referenced anywhere.
2. Check whether it contains requirements, architectural decisions, security rules, migration history, tests, configuration or important documentation.
3. Explain why deletion is necessary.
4. List every deleted file in the implementation report.

Never delete specifications, architectural decisions, security/audit documentation, migration history, tests, configuration or important documentation merely because they appear unused. Ask the product owner before destructive or hard-to-reverse changes not clearly required by the approved architecture.


Before deleting or replacing code, determine:
- who uses it,
- whether it is public API,
- whether data migration is needed,
- whether backward compatibility matters,
- whether tests cover it.

## 16A. Platform Independence and Data Integrity Rules

- Core domains (identity, organizations, RBAC, audit, notifications, billing, reporting, finance, funnel, AI, recommendations, optimization, actions) must contain no platform-specific logic. Platform code lives only in provider modules (MASTER §20 D19).
- Unavailable, unsupported or not-yet-synchronized data must never be stored or displayed as 0 (MASTER §21 A10).
- Derived metrics (ROAS, CPA, CTR, CPC, conversion rate, margin %, budget utilization, profit margin) are calculated from stored measurable values; any cached value must be reproducible (A5).
- Every outbound request to an externally supplied host goes through the SSRF-safe HTTP client (A11).
- The AI receives only validated business context prepared by the backend; it is never given database, API, billing, infrastructure, source code or execution access (A12).
- Every external mutation goes through the Action Engine (A13).

## 17. Completion Definition

A task is complete only when:
- implementation exists,
- tests exist where needed,
- checks pass or failures are explicitly documented,
- documentation is updated,
- security implications are addressed,
- no known critical issue remains.

## 18. Stop Conditions

The AI agent must stop and ask for clarification when:
- two specifications conflict,
- destructive migration is required without approval,
- external API behavior is uncertain,
- a security boundary is unclear,
- financial definitions are ambiguous,
- an action could spend money beyond configured limits,
- production data could be damaged.
