# Phase 9 — Creative Engine

**Status:** Not started · **Depends on:** Phase 8 · **Milestone:** M3

## Goal
AI-generated creative concepts and copy per platform, with versions, compliance notes and human approval.

## Prerequisite decisions
Creative scope for MVP (recommended: copy + user-uploaded assets; AI image generation later); object storage choice (S3-compatible abstraction).

## Milestones
1. Creative schema per platform (character limits from verified platform docs)
2. Generation from approved strategy; variants; rationale; compliance notes
3. Versioning and approval/rejection workflow (audited)
4. Asset upload to object storage with validation (type, size, malware scan where available)
5. Deterministic policy checks (length, prohibited terms list) before approval

## Exit criteria
Only approved creatives are selectable by the campaign builder; every approval is in the audit log.
