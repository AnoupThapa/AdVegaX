# Phase 10A — Action Engine

**Status:** Not started · **Depends on:** 1, 3, 4 · **Milestone:** M4

## Goal
The single, audited, idempotent gate through which every external mutation passes.

## Prerequisites
Write permissions/approvals from Google Ads and Meta (development/test level at minimum).

## Milestones
1. **Action catalogue** — closed set of action types (e.g. create campaign paused, pause, resume, set budget) with typed parameters and bounds
2. **Validation chain** — schema → business rules → policy → budget → risk → authorization → idempotency
3. **State machine** — `pending → approved → submitting → unknown → succeeded/failed`, persisted *before* any provider call
4. **Concurrency** — per-resource lock; re-read provider state before mutation
5. **Provider write adapters** — paused-first creation; provider validate-only where supported
6. **Unknown-outcome reconciliation** — look up resource before any retry; never blind-retry creates
7. **Verification & reverse actions** — confirm result; explicit compensating action, also via the engine
8. **Audit** — requester, approver, AI recommendation, validations, payload, platform/account, result

## Exit criteria
Duplicate-create, timeout, partial-failure and concurrent-action tests pass; no code path mutates a provider outside the engine.
