# Phase 16 — Desktop Install, Demo Data & Admin Portal: Plan

**Status:** ✅ **Approved 2026-10-28 (A35, "Approve all").** Implemented — see `PHASE_16_REPORT.md`. · **Date:** 2026-10-28

> You run the **whole application on your Windows desktop** (no Docker): database, API, background jobs, web app. It starts with **demo data** for every feature. Outside connections (platforms, AI, payments, email) stay **off** until you enter their keys in a new **Admin portal** — for you as the operator, separate from customer organizations.

## 1. Decisions (recommendations)

| # | Question | Recommendation |
|---|---|---|
| Q-16-1 | Install without Docker | One PowerShell script installs, with Windows' own `winget`: Python 3.12 + uv, Node.js LTS, PostgreSQL 16 and **Memurai Developer** (Redis-compatible for Windows, free for development). A second script sets up the database, settings and demo data; a third starts everything and opens the browser. |
| Q-16-2 | Demo data | Sign-in `demo@advegax.local`; organizations **Eve Zone** (agency client) and **Mediflex**, plus **Demo Agency**; their simulated Shopify store, Google Ads, Meta and GA4 accounts imported through AdVegaX's own simulators (the same ones the tests use); 90 days of figures; recommendations, a strategy, creatives, changes made through the Action Engine, autopilot runs, a trial plan, an agency grant. Re-runnable ("reset demo"). |
| Q-16-3 | AI in the demo | Sample answers from the simulator until you enter an Anthropic key in the Admin portal; then real AI. |
| Q-16-4 | Admin portal | **/admin**, only for **platform admins** (you; made with a command). Pages: **Keys & connections** (Shopify, Google Ads, Meta, GA4, Anthropic, Stripe, Amazon SES — each key stored **encrypted**, shown only as "set ••••1234", replaceable, never read back), **Feature switches** (billing, agency, autopilot, changes, AI, retention…), **Organizations & users** (read; suspend an organization), **System health**. Every change audited. Keys in the settings file still work and are overridden by the portal. |
| Q-16-5 | Admin sign-in | **Two-step sign-in** (an authenticator app code, TOTP) required for the Admin portal. |
| Q-16-6 | Delivery | Tasks 16-01 … 16-07, one report with your checklist. |

## 2. Tasks

| Task | Content |
|---|---|
| 16-01 | Demo seed command (`python -m app.demo.seed`, re-runnable), using the simulators; demo settings file |
| 16-02 | Windows scripts: `install.ps1`, `setup.ps1`, `start.ps1`, `stop.ps1`, `reset-demo.ps1`; background jobs on Windows (single-process worker) |
| 16-03 | Platform admins; two-step sign-in (TOTP, no new library) |
| 16-04 | Encrypted platform settings in the database (migration 0027); every process picks up changes without a restart |
| 16-05 | Admin API: keys, switches, organizations and users, health; audit |
| 16-06 | Admin web pages |
| 16-07 | Tests; `PHASE_16_REPORT.md` with your step-by-step "run it on your desktop" guide |

## 3. Security

Demo data and demo settings only on your desktop (refused when deployed). Admin keys encrypted with the existing key set; never returned; admin actions need a platform admin with a fresh two-step sign-in; audited; customer organizations can never reach /admin.

## 4. Rollback

The scripts change nothing in the repository's runtime; the Admin portal is additive (migration 0027 reversible); without stored keys the settings file is used as today.
