# Phase 11 — Optimization Engine

**Status:** Not started · **Depends on:** 6, 7, 8, 10A · **Milestone:** M4

## Goal
AI recommendations based on validated deterministic metrics, approved or rejected by users, executed only via the Action Engine.

## Milestones
1. Deterministic signal detection (anomalies, drop-offs, spend without profit) as AI input
2. Recommendation schema: type, explanation, confidence, assumptions, risks, affected resource, proposed action, expiry
3. Approve → creates action request (never direct execution); reject with reason
4. Staleness re-validation against current state at execution
5. Recommendation outcomes tracked for later evaluation

## Exit criteria
Every executed recommendation is traceable end-to-end (who requested, approved, what AI said, validations, result).
