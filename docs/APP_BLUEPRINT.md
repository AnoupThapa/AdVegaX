# AdVegaX — App blueprint (plain-language overview)

**Purpose of this document:** one place that explains what AdVegaX is, the problem it solves, who it is for, how it works, what exists today and what does not.
**Sources:** `MASTER_SPECIFICATION.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `PROJECT_STATUS.md`, the phase reports, and a run of the app with its demo data (2026-10-29).
**Labels:** **[Stated]** = written in the project's approved documents. **[My reading]** = an inference from them; confirm or correct it.

---

## 1. One-paragraph definition

AdVegaX is a web application (software as a service) for **online stores that advertise**. It connects a store (Shopify or WooCommerce), the ad accounts (Google Ads, Meta) and website analytics (Google Analytics 4), puts their numbers side by side, works out what the advertising **really earns after costs**, and has an AI **propose** changes that a **person approves** before anything is sent to an ad platform. Every change is recorded. **[Stated: MASTER_SPECIFICATION §1, §19]**

## 2. The problem it solves

A merchant who advertises has their facts scattered across tools that do not agree with each other:

| Today | What goes wrong |
|---|---|
| Sales are in the store; spend and "conversions" are in Google Ads and Meta; visits are in Google Analytics | Nobody sees one picture. Each ad platform reports its own results and counts the same sale in its own way, so adding them up overstates success |
| Ad platforms optimise for clicks and their own "ROAS" | An ad can look good while the business loses money once product cost, refunds and fees are counted |
| Deciding what to change takes expertise and time | Small teams guess, or change budgets too late |
| AI tools can act on ad accounts | A wrong or invented number can spend real money |
| Agencies manage many clients in many logins | Hard to keep work separate, audited and accountable |

**AdVegaX's answer [Stated: D3, D17, §4]:** optimise for **profitable growth**, not clicks. Calculate the money figures in ordinary code (never with the AI). Let the AI explain and propose, but never act on its own. Keep a record of who approved what.

## 3. Who it is for

**[Stated]** the product speaks of "a merchant", "the business" and "agency accounts"; roles are Owner, Admin, Manager, Analyst, Viewer; it supports several stores, ad accounts, currencies and time zones per business.

**[My reading] — the customers this implies:**

1. **Primary: independent online stores and small to mid-size e-commerce brands** that sell through Shopify or WooCommerce and spend money on Google or Meta ads. Typical user: an owner or marketing manager, with no data analyst, who wants clear answers on profitability and safe help deciding what to change.
2. **Secondary: marketing agencies** that run advertising for several stores. The agency mode lets an agency organization work inside a client's organization, with the client's permission, and with every action shown in the client's audit log.
3. **Within one business:** the Owner (decides and pays), the Manager (runs campaigns and connections), the Analyst (reads reports and recommendations), the Viewer (read-only).

**Not for [Stated: §16]:** anyone wanting fake engagement, unrestricted autonomous spending, or tools that get around platform rules.

**Open questions for you** (not decided in the documents): launch country and currencies (the demo uses Australian dollars and Sydney time), pricing and plans (Q14), which store size you target first, and whether agencies are a launch audience or a later one (Q15).

## 4. How a customer uses it (the journey)

1. Create an account and verify the email address; create an **organization** (the business).
2. **Connect** the store, then Google Ads, Meta and Google Analytics. Connections only read data; the user chooses which discovered accounts belong to this organization.
3. AdVegaX imports products, orders and refunds, and daily ad and visit figures.
4. **Overview and Reports** show sales, ad spend, profit after ad spend, blended ROAS and cost per order, by day, channel, campaign and product. Where a figure is missing (for example product costs were never entered) the screen says so instead of showing zero.
5. **Funnel** follows the path from impression to purchase and where people drop off.
6. **Recommendations**: once a day AdVegaX compares each running campaign with its own past and proposes changes, each with a reason, an expected result, assumptions and confidence.
7. **Strategies and Creatives**: pick a product, set an objective and budget; the AI drafts a strategy and ad copy, which the user edits and approves. The **campaign builder** prepares a draft campaign.
8. **Changes**: nothing reaches an ad platform until a person with the right role approves it. Approved changes are re-checked, sent through the official API, verified, and logged.
9. Optional **autopilot**: an owner allows certain kinds of change, within hard limits (daily spend, maximum budget change, minimum campaign age, actions per day, cooldown).
10. **Billing** (subscription), **Members** (invitations and roles) and the **audit log** run the organization.

## 5. The three operating modes [Stated: §10]

| Mode | What the AI does | Who acts |
|---|---|---|
| Manual | Analyses and recommends | The user, on the platform |
| Assisted | Prepares the change | The user approves each one |
| Autopilot | Executes only allowed kinds of change inside hard limits | The system, within limits the owner set |

## 6. Main parts of the product (as seen in the app)

| Area | Pages | What it is for |
|---|---|---|
| Public | Home, Sign in, Create account, password reset, email verification | Entry; the home page is the only one meant for search engines |
| Performance | Overview, Reports, Funnel, Analytics | Understand what is earned and where people drop off |
| Marketing | Advertising, Strategies, Creatives, Recommendations, Changes | Decide and act, with approvals |
| Data | Stores (and products), Connections | Link and monitor the platforms |
| Organization | Members, Settings (including autopilot), Billing, Clients (agencies) | Run the business account |
| Account | Account security | Sessions and password |
| Operator | Admin portal (`/admin`) | For the people who run the installation: encrypted keys, feature switches, organizations, health |

## 7. How it works inside (simple version)

```
Store / Google Ads / Meta / GA4
        │   (official APIs only, read-only connections)
        ▼
   Connectors  ──►  Normalised data  ──►  Money and funnel figures
                                              (calculated in code, never by the AI)
                                                     │
                                                     ▼
                                  AI gets only checked business context
                                                     │
                                                     ▼
                       AI proposal ──► rules, budget and risk checks ──► person approves
                                                     │
                                                     ▼
                              Action Engine ──► platform API ──► verification ──► audit log
```

Key rules the build follows [Stated: §4, §9, §21]:
- **Each organization's data is isolated**, in the application and in the database itself (row-level security).
- **The AI has no direct access** to the database, ad accounts, billing or the internet; its output is checked against a strict format and a fixed list of allowed actions.
- **Platform credentials are encrypted** and never shown to the browser or the AI.
- **Unavailable data is never turned into zero.**
- **Every outgoing change goes through one gate** (the Action Engine) and is logged.
- **Roles** are enforced on the server, not just hidden in the screen.

## 8. Technology [Stated: §3]

Backend: Python, FastAPI, SQLAlchemy, PostgreSQL, Redis, Celery (background jobs). Frontend: Next.js, React, TypeScript. Deployed as Docker containers; a Fly.io set-up for staging exists. Desktop demo: Windows PowerShell scripts run everything locally without Docker.

## 9. Where the project stands (2026-10-29)

**Built and awaiting your review [PROJECT_STATUS]:** accounts and sessions, organizations and roles, connection framework, Shopify and WooCommerce stores, Google Ads, Meta, GA4, unified analytics and finance, funnel, AI planner, creative engine, Action Engine, campaign builder, optimisation, autopilot, Stripe billing, agency mode, staging set-up, desktop install with demo data and an Admin portal. The reports quote about 2,100 backend and 590 frontend tests and 21 browser tests.

**Important limits you should know about:**
- **Everything you see in the demo is simulated.** The demo organizations (Eve Zone, Mediflex, Demo Agency) are filled from AdVegaX's own simulators. Nothing has been checked against a live Shopify, Google, Meta or Stripe account yet; the reports list those "Step 0" checks as pending.
- **No AI key is configured**, so recommendations say "Explained by AdVegaX's own rules: the AI is not set up". An Anthropic key is needed for the AI strategy and creatives against a real model.
- **Billing has no Stripe key**, so "Choose a plan" is refused until test keys are added.
- **Production and staging are not running.** The staging set-up needs your Fly.io, database and Redis accounts and a domain.
- **The Windows desktop scripts** were first run on your PC and needed several fixes; they are better now but still lightly tested.
- **The redesign (Phase 17) is partly done:** navigation, home page, overview tiles and some shared styling. Most pages still use the older look. See `phases/PHASE_17_PLAN.md`.

## 10. How the business can earn money [Stated: §15, Phase 13]

Subscriptions with trials, plans, usage limits and entitlements, paid through Stripe; separate agency accounts managing several client organizations. Prices and plan contents are **not decided** (Q14).

## 11. Main risks to keep in view

| Risk | Why it matters |
|---|---|
| Platform approvals (Google Ads developer token, Meta App Review and business verification, Shopify public-app review) | Can take weeks and block real connections; the project notes say to start early |
| Real data is messier than the simulator | The first live connections will surface differences |
| Missing product costs | Profit figures stay "not available" until merchants enter costs; the demo already shows this |
| Trust | The product's selling point is explainable, approved changes; any wrong figure damages it, so the money maths is tested separately from the AI |
| Scope | A very broad product for a small team; the phased plan exists to keep it manageable |

## 12. Decisions that are yours to make

1. Who the first customers are (single-store merchants, agencies, or both) and the launch country and currency.
2. Plans and pricing (Q14) and whether the public home page shows them.
3. Domain name, hosting provider and region, and email provider (Q16) so staging can start.
4. Which platform approvals to apply for first.
5. Whether the AI provider is Anthropic (the code is prepared for it) and how much creative generation to allow (Q12).
6. Public legal pages (privacy, terms): the text must come from you or your lawyer.

## 13. Glossary

- **Organization:** one business's workspace; users belong to organizations through memberships.
- **Connection:** the permission you give AdVegaX on a platform; **resource**: a store or ad account found through it; **link**: your choice to use it in this organization.
- **ROAS:** revenue divided by ad spend. **Blended ROAS** uses the store's sales and all ad spend. **Platform ROAS** is what one ad platform reports for itself.
- **CPA / cost per order:** ad spend divided by orders.
- **Action Engine:** the single gate through which every change to an ad account passes.
- **Autopilot:** optional automatic changes inside limits an owner sets.
- **Audit log:** the record of who did what, when and why.
- **Row-level security (RLS):** a database feature that keeps one organization's rows invisible to another.
