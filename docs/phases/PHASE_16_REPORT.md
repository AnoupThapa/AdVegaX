# Phase 16 — Report (Desktop Install, Demo Data & Admin Portal)

**Status:** Implemented — awaiting your review and your first run on Windows.
**Plan:** `PHASE_16_PLAN.md`, approved 2026-10-28 (A35, "Approve all").

## 1. Summary

- **The whole app on your Windows desktop, without Docker.** Three scripts in `scripts\windows\`:
  - `install.ps1` installs the tools;
  - `setup.ps1` sets up the database, settings and demo data, and builds the web app;
  - `start.ps1` starts the API, background jobs, scheduler and web app, and opens your browser.
  - `stop.ps1`, `reset-demo.ps1` and `make-admin.ps1` complete the set.
- **Demo data for every feature.** It comes from AdVegaX's own simulators — the same ones the tests use — so nothing leaves your computer:
  - **Eve Zone:**
    - a Shopify store, Google Ads, Meta and Google Analytics, with recent figures;
    - recommendations;
    - an AI strategy, creatives and a campaign draft;
    - changes made through the Action Engine.
  - **Mediflex:** a WooCommerce store, Google Ads with autopilot that has made a change, and a Starter plan.
  - **Demo Agency:** has Manager access to Eve Zone.
- **Emails** — sign-up links, invitations, password resets — are written as files to `var\mail` instead of being sent.
- **Admin portal** at `/admin`, for you as the operator. Customers can never open it.
  - It needs a code from an authenticator app (two-step sign-in).
  - **Keys and connections:** Shopify, Google, Meta, Anthropic AI, Stripe and Amazon SES.
    - Keys are stored **encrypted** and never shown again (only "••••1234").
    - Each key can be replaced, or reset to the settings file.
  - **Feature switches.**
  - **Organizations:** suspend or reactivate.
  - **People** and **System health**.
  - Every change is audited.
  - Saved values apply **the next time AdVegaX starts**: `stop.ps1`, then `start.ps1`.

## 2. Run it on your desktop (step by step)

1. Open **Terminal (Admin)**: right-click the Start button. Then paste, one line at a time:

   ```
   Set-ExecutionPolicy -Scope Process Bypass
   cd "$HOME\Downloads\Tools\Advegax"
   .\scripts\windows\install.ps1
   ```

   This installs Python 3.12, uv, Node.js, Memurai (Redis for Windows) and PostgreSQL 16 with winget. It takes 5–15 minutes.
2. **Close the window and open a new, normal PowerShell window.** Then:

   ```
   Set-ExecutionPolicy -Scope Process Bypass
   cd "$HOME\Downloads\Tools\Advegax"
   .\scripts\windows\setup.ps1
   ```

   This takes 10–20 minutes the first time (packages, demo data, building the web app).
3. Start AdVegaX:

   ```
   .\scripts\windows\start.ps1
   ```

   Your browser opens **http://localhost:3000**. Sign in with:
   - **demo@advegax.local** — owns Eve Zone and Mediflex, and is an administrator;
   - **agency@advegax.local** — owns Demo Agency.

   The password for both is **AdVegaX-demo-2026**.
4. **Admin portal:** click **Admin** at the top, then **Start**. In your authenticator app, add an account using the key shown, then enter the 6-digit code.
5. **Stop:** `.\scripts\windows\stop.ps1`. **Start again from fresh demo data:** `.\scripts\windows\reset-demo.ps1`.

If a step fails, send me the message on the screen, or the files in `var\logs`.

## 3. Test results

| Suite | Result |
|---|---|
| Backend `make check` | ✅ full run 2,125 tests: 2,123 passed and 2 failed. Both failures were in the tests themselves, not the app: a demo-command test leaked a setting into a later test, and the organization sweep tried the new /admin route. Both are fixed, and those test files pass on rerun. Coverage 95.30 % |
| Frontend `npm run check` | ✅ 591 passed (branch coverage 85.1 %) |
| Browser | ✅ 21 passed (the whole suite, with the new Admin link in the header) |
| Demo data | ✅ the full demo seed runs start to finish on a fresh database (Linux), and the web app shows it (screenshots sent with this report). The simulated shops are small (a handful of orders), so some figures are modest or say "Some products have no cost" — as with a real shop before its costs are filled in |
| Windows scripts | ⚠️ **not run on Windows yet**: this environment cannot run PowerShell. Your first run is the test (§5) |

New tests:

- `tests/api/test_admin_api.py`
- `tests/unit/test_folder_email.py`
- `tests/unit/test_demo_seed.py`
- `frontend/tests/features/admin.test.tsx`

## 4. Database

Migration **0027** (reversible) adds `platform_admins` and `platform_settings`, plus two narrow reads and one update for the system role. See DATABASE_SCHEMA §14I.

## 5. Deviations and limitations

1. **Changes apply after a restart**, not live. That is simpler and safer: each part of AdVegaX reads the keys once, when it starts. The Admin page and System health say when a restart is needed.
2. **The demo command** is `uv run python -m demo.seed`, kept outside `app\`, so it is never part of a server image. On the desktop it is run for you by `setup.ps1`.
3. **The Windows scripts have not been tested on Windows yet.** The exact winget names of the packages may need adjusting on the first run.
4. **The demo trial lasts 90 days.** Billing is on but has no Stripe key, so "Choose a plan" is refused until you enter test keys in the Admin portal.
5. **Documentation fix:** the API and database specifications had each lost a section heading in Phase 14 ("20. Webhooks", "14. AI Tables"). Both are restored.

## 6. Your checklist

**A. Try it:**

1. Do §2, steps 1–3.
2. Click through every page:
   - in **Eve Zone**: Overview, Reports, Funnel, Strategies, Creatives, Recommendations, Changes, Stores, Advertising, Analytics, Billing, Settings;
   - in **Mediflex**: autopilot, under Settings;
   - as **agency@advegax.local**: Clients.
3. **Admin portal:** set up two-step sign-in. Switch a feature on, enter a test key, then restart.
4. Tell me what to change in how it looks and works (UI/UX). Each change can be a small next step.

**B. Decide:** the deviations in §5.

**C. Documents:**

- this report;
- API_SPECIFICATION §19P;
- DATABASE_SCHEMA §14I.
