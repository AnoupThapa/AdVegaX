# AdVegaX — Database Schema Specification

> **Amended 2026-10-08** for decisions D1–D22 (MASTER_SPECIFICATION.md §20) and Phase 0 approvals A1–A14 (§21).

This document is the **target data model**. Tables are created only in the phase that implements their functionality (A4); the "Introduced" column in §0 is authoritative. Exact Phase 1 column definitions, constraints and indexes are fixed in the approved phase plan before migrations are written.

## 0. Table introduction by phase

| Phase | Tables |
|---|---|
| 1A | users, user_password_credentials, sessions, user_action_tokens, organizations, memberships, invitations, audit_logs, security_events, email_outbox |
| 1B | external_connections, external_connection_credentials, external_resources, organization_resource_links, job_runs |
| 2A / 2B | **as built (migrations 0007–0011):** stores, products, product_variants (incl. inventory), product_cost_history, orders (incl. hashed customer key), order_items, sales_entries, refunds, refund_items, commerce_sync_state, webhook_events, financial_daily (store components) — see §4A |
| 3–4 | **as built (migrations 0012–0013):** ad_accounts (resource extension), ad_budgets, ad_campaigns, ad_groups, ads, ad_performance_daily, ad_sync_state — see §4B. Keywords and audience_targets come with the phases that use them |
| 5 | **as built (migrations 0014, 0015):** analytics_properties (resource extension), analytics_daily (daily aggregates in three views), analytics_sync_state — see §12 (decision Q11, A23) |
| 6 | fx_rates, metric_definitions, store_cost_rules; financial_daily gains ad-spend components |
| 7 | funnel_daily |
| 8–9 | ai_models, prompt_versions, ai_runs, campaign_strategies, creatives |
| 10A | actions, approvals, idempotency_keys |
| 11 | recommendations |
| 12 | automation_policies |
| 13 | plans, entitlements, usage_records, billing_customers, subscriptions, invoices |
| 14 | agency grants |
| later | notifications (in-app), user_identities (external IdPs), user_mfa_factors (MFA/passkeys) |


## 1. Database

Primary database: PostgreSQL.

Use UUIDs for internal primary identifiers unless there is a documented reason otherwise.

Use UTC timestamps for stored event timestamps.

Money should use fixed-precision numeric/Decimal semantics, never floating-point arithmetic.

## 2. Core Identity and Organization Tables (Phase 1A — implemented)

Implemented by migrations `0001_identity`, `0002_organizations`. All timestamps are `timestamptz` (UTC). Primary keys are application-generated UUIDs. Constraint and index names follow the naming convention in `backend/app/db/base.py`.

Global identity tables (`users`, `user_password_credentials`, `sessions`, `user_action_tokens`) are **not tenant-owned** and have no RLS (§19); they are reachable only through the identity domain.

### users
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| email | varchar(254) NOT NULL | unique (`uq_users_email`); check `email = lower(email)` |
| display_name | varchar(120) | |
| status | varchar(16) NOT NULL default `active` | check: active, disabled |
| email_verified_at | timestamptz | null until verified |
| created_at, updated_at | timestamptz NOT NULL default now() | |

### user_password_credentials
| Column | Type | Notes |
|---|---|---|
| user_id | uuid PK, FK → users ON DELETE CASCADE | one password credential per user |
| password_hash | text NOT NULL | Argon2id; parameters encoded in the hash; upgraded on login |
| password_changed_at | timestamptz NOT NULL | |
| created_at, updated_at | timestamptz NOT NULL | |

Credentials are separate from `users` so external identities (`user_identities`) and MFA factors/passkeys (`user_mfa_factors`) can be added later without redesign (A8).

### user_action_tokens
Single-use tokens for email verification, password reset and invitation acceptance. Only SHA-256 hashes are stored.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| purpose | varchar(32) NOT NULL | check: email_verification, password_reset, invitation |
| token_hash | varchar(64) NOT NULL | unique |
| user_id | uuid FK → users ON DELETE CASCADE | verification/reset tokens |
| email | varchar(254) | address the token was issued for (must still match on use) |
| organization_id | uuid FK → organizations ON DELETE CASCADE | invitation tokens (added in 0002) |
| invitation_id | uuid FK → invitations ON DELETE CASCADE | invitation tokens (added in 0002) |
| expires_at | timestamptz NOT NULL | from `EMAIL_VERIFICATION_TTL`, `PASSWORD_RESET_TTL`, `INVITATION_TTL` |
| consumed_at | timestamptz | set atomically on use |
| invalidated_at | timestamptz | set when a newer token of the same scope is issued |
| created_at | timestamptz NOT NULL | |

Indexes: `(user_id, purpose)`, `organization_id`, `invitation_id`.

### organizations
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | varchar(120) NOT NULL | |
| slug | varchar(63) NOT NULL | unique; check `^[a-z0-9]+(-[a-z0-9]+)*$` |
| default_currency | varchar(3) NOT NULL | check ISO-4217 shape `^[A-Z]{3}$` |
| default_timezone | varchar(64) NOT NULL | IANA name, validated by the API (reporting time zone) |
| status | varchar(16) NOT NULL default `active` | check: active, suspended |
| created_by_user_id | uuid FK → users ON DELETE SET NULL | indexed |
| created_at, updated_at | timestamptz NOT NULL | |

### memberships
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid NOT NULL FK → organizations ON DELETE CASCADE | |
| user_id | uuid NOT NULL FK → users ON DELETE CASCADE | |
| role | varchar(16) NOT NULL | check: owner, admin, manager, analyst, viewer |
| status | varchar(16) NOT NULL default `active` | check: active, suspended, removed (removal is soft) |
| created_at, updated_at | timestamptz NOT NULL | |

Unique `(organization_id, user_id)`; index `(user_id, status)`. Invariant (service-enforced with row locks): every organization keeps at least one active owner.

### invitations
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid NOT NULL FK → organizations ON DELETE CASCADE | |
| email | varchar(254) NOT NULL | lower-case check |
| role | varchar(16) NOT NULL | role check as memberships |
| invited_by_user_id | uuid FK → users ON DELETE SET NULL | indexed |
| status | varchar(16) NOT NULL default `pending` | check: pending, accepted, revoked, expired |
| expires_at | timestamptz NOT NULL | |
| accepted_at | timestamptz | |
| accepted_by_user_id | uuid FK → users ON DELETE SET NULL | indexed |
| created_at, updated_at | timestamptz NOT NULL | |

Indexes: `(organization_id, status)`; partial unique `(organization_id, email) WHERE status = 'pending'`.

## 3. Sessions / Security (Phase 1A — implemented)

### sessions
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid NOT NULL FK → users ON DELETE CASCADE | indexed; partial index on active sessions |
| token_hash | varchar(64) NOT NULL | unique; SHA-256 of the 256-bit cookie token |
| auth_method | varchar(32) NOT NULL default `password` | later: oauth, sso |
| assurance_level | varchar(32) NOT NULL default `single_factor` | later: mfa (step-up) |
| created_at, last_used_at | timestamptz NOT NULL | `last_used_at` updated at most every `SESSION_TOUCH_INTERVAL` |
| idle_expires_at | timestamptz NOT NULL | sliding, from `SESSION_IDLE_TIMEOUT`; never beyond absolute |
| absolute_expires_at | timestamptz NOT NULL | from `SESSION_ABSOLUTE_TIMEOUT`; check idle ≤ absolute |
| revoked_at, revoked_reason | timestamptz, varchar(64) | logout, logout_all, rotated, user_revoked, password_changed, password_reset |
| ip_hash | varchar(64) | keyed hash; raw IPs are never stored |
| user_agent_summary | varchar(200) | |

### security_events (migration 0003)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK → organizations ON DELETE SET NULL | indexed |
| user_id | uuid FK → users ON DELETE SET NULL | index `(user_id, created_at)` |
| event_type | varchar(64) NOT NULL | user_registered, registration_existing_email, email_verified, email_verification_resent, login_succeeded, login_failed, logout, logout_all, session_revoked, password_reset_requested, password_reset_completed, password_changed |
| ip_hash | varchar(64) | keyed hash |
| user_agent_summary | varchar(200) | |
| correlation_id | varchar(64) | |
| metadata | jsonb NOT NULL default `{}` | scrubbed |
| created_at | timestamptz NOT NULL | index `(event_type, created_at)` |

The API role may only insert; reading is a system operation.

### email_outbox (migration 0004)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| organization_id | uuid FK → organizations ON DELETE SET NULL | indexed |
| template | varchar(64) NOT NULL | email_verification, account_exists, password_reset, password_changed, invitation, security_notice |
| recipient | varchar(254) NOT NULL | |
| payload | jsonb NOT NULL | template variables incl. single-use links; **cleared once sent or permanently failed** |
| status | varchar(16) NOT NULL default `pending` | check: pending, sent, failed (rows are locked during delivery, so no separate "sending" state) |
| attempts | integer NOT NULL default 0 | |
| last_error | text | short error class only |
| next_attempt_at | timestamptz NOT NULL default now() | exponential backoff from `EMAIL_RETRY_BASE_DELAY` |
| provider_message_id | varchar(255) | |
| sent_at | timestamptz | |
| created_at, updated_at | timestamptz NOT NULL | index `(status, next_attempt_at)` |

The API role may only insert; the worker (`advegax_system`) reads and updates.

## 4. External Connections and Resources (Phase 1B — implemented, migrations 0005–0006)

Approved model A6/A16: **Organization owns the connection; a User authorizes it.** Connection → discovered resources → explicit organization links. If the same platform account must serve two organizations, each organization creates its own connection (credentials are never shared across organizations) — **except** for platforms that allow only one live token per account, such as Shopify: there a platform account may be live in only one organization at a time (Q6, `external_account_id`, §4A).

All five tables have RLS **enabled and forced** with tenant policies for `advegax_app` (SELECT/INSERT/UPDATE; **no DELETE**). Child tables reference their parent with a **composite foreign key on `(organization_id, id)`**, so a row can never point at another tenant's parent.

### external_connections (0005; `external_account_id` added in 0007)
- id (uuid PK), organization_id (FK organizations, cascade)
- provider (varchar 32), auth_scheme (`oauth2` | `api_key` | `app_key`)
- authorized_by_user_id (FK users, set null)
- status (`active` | `expired` | `revoked` | `error`, default active)
- granted_scopes (text[]), external_account_label
- last_error_code, last_error_at (code only — never provider messages)
- revoked_at, created_at, updated_at
- Unique (organization_id, id); index (organization_id, provider)

### external_connection_credentials (0005)
- connection_id (PK; composite FK → external_connections(organization_id, id), cascade)
- organization_id
- ciphertext (bytea), wrapped_data_key (bytea), key_version (int) — **all three null together** (check constraint); nulled on disconnect
- token_expires_at, refresh_expires_at, last_refreshed_at, created_at, updated_at

Envelope encryption (AES-256-GCM, associated data binds organization + connection + provider) — see `SECURITY.md §8`. Credentials are never returned through API responses, logs, audit records, errors, the UI or AI context. `advegax_system` has SELECT/UPDATE only for key rotation (re-wrapping data keys).

### external_resources (0005)
Resources discovered through a connection (store, ad account, analytics property, business asset).
- id, organization_id, connection_id (composite FK → external_connections, cascade)
- kind (`store` | `ad_account` | `analytics_property` | `business_asset`), provider, external_id (text)
- display_name, currency, timezone
- accessible (still reachable through the connection), capabilities (jsonb, capability → bool)
- discovered_at, last_seen_at, last_synced_at
- Unique (organization_id, id); unique (connection_id, kind, external_id); index (organization_id, kind)

### organization_resource_links (0005)
Explicit linking; history kept for relinking/reassignment.
- id, organization_id, external_resource_id (composite FK → external_resources, cascade)
- status (`active` | `unlinked`)
- linked_by_user_id, linked_at, unlinked_by_user_id, unlinked_at
- unlink_reason (`user` | `connection_revoked` | `resource_inaccessible`)
- Partial unique index: at most one `active` link per resource

### job_runs (0006)
Durable record and source of truth for background work.
- id, organization_id (nullable for system jobs; FK organizations, cascade)
- job_type, subject_type, subject_id
- status (`queued` | `running` | `succeeded` | `failed` | `dead`)
- attempts, max_attempts, next_attempt_at, last_error_code (code only)
- correlation_id, requested_by_user_id
- started_at, finished_at, created_at, updated_at
- Indexes (status, next_attempt_at), (organization_id, created_at)
- RLS: tenant policies for `advegax_app`; `advegax_system` SELECT/UPDATE across tenants to claim, retry and recover jobs (handlers then run under the job's tenant context).

## 4A. Commerce, webhook intake and daily figures (Phase 2A — migration 0007)

Platform-neutral tables (D4, D19); providers map into them. **Tenant tables** (`stores`, `products`, `product_variants`, `product_cost_history`, `orders`, `order_items`, `sales_entries`, `refunds`, `refund_items`, `commerce_sync_state`, `financial_daily`): RLS enabled and forced; `advegax_app` policies for SELECT/INSERT/UPDATE **and DELETE** (needed for erasure requests and re-imports; still limited to the current organization); composite `(organization_id, parent_id)` foreign keys everywhere. Optional references from financial history (order line → variant, sales entry / refund line → order line) do **not** cascade, so deleting a product never deletes order history. Money is `NUMERIC(20,6)` in the store's currency; missing values are NULL with a source/availability marker, never 0 (A10).

| Table | Key columns and rules |
|---|---|
| `stores` | resource extension (`external_resource_id` unique, composite FK); provider, external_store_id, domain, name, currency (3), timezone, status (`importing`/`active`/`disconnected`/`error`), `history_from` (Q9), `first_import_completed_at`; unique (organization, provider, external_store_id) |
| `products` | store FK; external_product_id (unique per store), title, handle, product_type, vendor, status (`active`/`draft`/`archived`/`deleted`), `external_updated_at` (an older update never overwrites a newer one) |
| `product_variants` | product + store FKs; external_variant_id (unique per store), external_inventory_item_id, title, sku, price; inventory: `inventory_tracked`, `inventory_available` (summed across locations; NULL = not tracked / not synchronized), `inventory_synced_at`; `deleted` flag (soft delete) |
| `product_cost_history` | variant FK; `unit_cost` (NULL = no cost from that moment), currency, `effective_from` (unique per variant), source (`platform`/`import_snapshot`), `recorded_at` |
| `orders` | store FK; external_order_id (unique per store), order_number, currency, `ordered_at`, `cancelled_at`, financial_status; display amounts (gross, discount, shipping, tax, refund, total); **`customer_key`** (one-way, organization-keyed hash — no names, emails, phones or addresses, Q8); `country_code` (2); `external_updated_at` |
| `order_items` | order FK; variant (optional, non-cascading); external_line_item_id (unique per order), title, sku, quantity, unit_price; `unit_cost` + `cost_source` (`order_time`/`import_time`) — both NULL or both set |
| `sales_entries` | one sale or reversal with its own `happened_at`; `agreement_reason` (`order`/`order_edit`/`refund`/`return`/`other`, the platform agreement's reason — 0008), `action` (`order`/`return`/`update`/`other`, the sale's action — 0008), `line_type` (`product`/`shipping`/`duty`/`fee`/`additional_fee`/`adjustment`/`tip`/`gift_card`/`other` — 0008), quantity, signed `amount` (sale total after taxes and discounts), `discount_amount` (before taxes), `tax_amount`, currency; external agreement/sale/line-item ids (sale unique per store; the line-item id resolves `order_item_id` after a bulk import); optional order line (non-cascading). Source of §10 figures |
| `refunds`, `refund_items` | refund with `processed_at`, total, currency; lines with quantity, subtotal, restocked |
| `commerce_sync_state` | one row per store: import progress (0–100), bulk operation id/kind, last reconciliation times, last error code |
| `financial_daily` | per store, `day` (store time zone), currency, `definition_version` (unique per store/day/version); additive components: gross_sales, discounts, sales_reversals, net_sales, shipping, taxes, duties, fees, total_sales, orders_count; **`cogs` NULL exactly when `uncosted_lines > 0`** (check constraint), `costed_net_sales` for coverage; `other_currency_orders` (0011: orders in another currency placed or refunded that day — never summed; the day's figures are "not available" while it is above 0, Q-2B-5); `computed_at`. Only counted orders contribute (`orders.excluded_reason` IS NULL). Ratios computed on read (A5). Ad-spend components are added in Phase 6. **Filled from 2A-08** by `app/domains/finance/service.py` (rebuilt for the affected store-local days after every import, reconciliation and order webhook); the definitions are in `app/domains/finance/definitions.py` (`finance-v1`) |
| `webhook_events` | **system role only** (no app-role grants). Metadata only — provider, `webhook_id` (unique per provider, duplicate deliveries rejected), topic, external_account_id, object id, `object_updated_at`, `triggered_at`, `received_at`, resolved organization (nullable), status, processed_at, error_code. **No body column**: payload personal data is never stored |
| `external_connections.external_account_id` | platform account id (e.g. shop domain); partial unique index `(provider, external_account_id)` where not NULL and status ≠ `revoked` — one live connection per account across organizations (Q6) |

**0011 (2B-07, Phase 2B)** is additive: `financial_daily.other_currency_orders` (integer, default 0, ≥ 0). Downgrade to 0010 drops it.

**0010 (2B-02, Phase 2B)** is additive. It adds:
- On `stores`: `site_url` (normalized base URL; WordPress may live in a sub-folder), `platform_version`, `health_code` and `health_checked_at` (plain-language health of a self-hosted store), and `counted_statuses` (the order statuses counted in the figures, Q-2B-2).
- On `orders`: `excluded_reason` (`status` / `other_currency`: kept but not counted).
- On `commerce_sync_state`: `import_cursor` (the provider's opaque cursor for the next page of a paged import, ≤ 2048 characters) and `import_counts` (records applied by the running chain, JSONB).

**0009 (2A-07)** adds `commerce_sync_state.sync_mode` (`initial`/`reconcile`/`deep`) and `sync_started_at` (the next reconciliation's starting point).

**0008 (2A-06)** aligns the value lists with Shopify's verified enums: product status gains `unlisted`; the sales-entry lists above; `commerce_sync_state.import_job_id` names the only import step allowed to continue.

System-role grants added in 0007 (narrow, read-only): `SELECT` on `stores` (route a webhook to its store before a tenant context exists) and on `external_connections` (cross-organization live-account check before a token exchange). The system role cannot read orders, products or figures.

## 4B. Advertising (Phase 3 — migrations 0012–0013)

Platform-neutral, designed against Google Ads and Meta (PHASE_03_PLAN §8): Google "ad group" and Meta "ad set" are both `ad_groups`. Every table is tenant-owned with composite `(organization_id, parent_id)` keys, forced row-level security and `advegax_app` policies for SELECT/INSERT/UPDATE/DELETE. Money is `NUMERIC(20,6)` in the **ad account's** currency; days are in the ad account's time zone; a measure the platform did not provide is NULL, never 0 (A10).

| Table | Content |
|---|---|
| `ad_accounts` | extension of a linked `ad_account` resource (unique per resource; and per organization, provider and external account id): name, currency, time zone, AdVegaX `status` (`importing`/`active`/`disconnected`/`error`), `platform_status` (`active`/`not_enabled`/`cancelled`/`suspended`/`closed`), `history_from`, `first_import_completed_at`, `health_code` and `health_checked_at` (plain message keys, never raw errors) |
| `ad_budgets` | per account: external id, name, `level` (`campaign`/`ad_group`), `period` (`daily`/`lifetime`), `amount` (NULL when the platform gives none, never 0), currency, `shared` |
| `ad_campaigns` | per account: external id, name, `status` (`active`/`paused`/`archived`/`removed`), `platform_type` (shown, never computed on), bidding strategy type, start/end dates, optional budget (non-cascading), `provider_extensions` (display only) |
| `ad_groups` | per campaign: external id, name, status, platform type, optional budget (Meta ad sets), extensions |
| `ads` | per ad group: external id, optional name, status, platform type, extensions |
| `ad_performance_daily` | one row per account, `level` (`account`/`campaign`/`ad_group`/`ad`), `entity_key` (the platform id; `'account'` at the account level; for Google ads `<ad group id>~<ad id>`, since an ad is identified within its ad group) and `day`: impressions, clicks, cost, conversions (decimal), conversion value, currency, `source` (`platform_reported` only in Phase 3), `fetched_at`; optional non-cascading links to the campaign, ad group and ad. Levels are stored as reported and never added into each other |
| `ad_sync_state` | one row per account: import progress, sync mode (`initial`/`quick`/`nightly`/`weekly`), the job allowed to continue, an opaque cursor, last quick / nightly / weekly runs, last error |

Removed structure is kept (`status = removed`) so history stays readable. A day never read has no row ("not synced yet"); a day read with no activity has real zeros.

**0012** also adds three discovery details to `external_resources` (any provider, never secrets): `unavailable_reason` (why it cannot be linked, e.g. a manager or cancelled account), `group_path` (the groups it sits in, for display) and `access_hint` (an opaque value the provider needs to reach it — Google Ads: the manager account to sign in through). Downgrade to 0011 removes all of the above.

**0013** (3-07) lets the system role list imported ad accounts for the sync scheduler: `SELECT` on **four columns only** of `ad_accounts` (`id`, `organization_id`, `provider`, `first_import_completed_at`), with a system-role read policy. Names, figures and everything else stay readable only under the account's own tenant context. Downgrade to 0012 revokes it.

## 5. Stores

> Original target model, kept for reference. **As built in Phase 2A: see §4A.**

### stores
Commerce-specific extension of an external resource of kind `store`.
- id
- organization_id
- external_resource_id
- provider
- external_store_id
- domain
- name
- currency
- timezone
- status
- created_at
- updated_at

Unique:
- organization_id + provider + external_store_id

## 6. Products

> Original target model, kept for reference. **As built in Phase 2A: see §4A.**

### products
- id
- organization_id
- store_id
- external_product_id
- title
- description
- handle
- product_type
- vendor
- status
- price
- currency
- cost
- landing_url
- image_url
- created_at
- updated_at

### product_variants
- id
- organization_id
- product_id
- external_variant_id
- sku
- title
- price
- cost
- inventory_quantity
- currency
- status
- created_at
- updated_at

Indexes:
- organization_id
- product_id
- external identifiers
- sku where appropriate

## 7. Orders

> Original target model, kept for reference. **As built in Phase 2A: see §4A.**

### orders
- id
- organization_id
- store_id
- external_order_id
- order_number
- status
- currency
- gross_amount
- discount_amount
- tax_amount
- shipping_amount
- refund_amount
- net_amount
- ordered_at
- updated_at
- raw_reference/metadata

### order_items
- id
- organization_id
- order_id
- product_id
- variant_id
- external_line_item_id
- quantity
- unit_price
- discount_amount
- product_cost
- line_total

## 8. Advertising Accounts

### ad_accounts
Advertising-specific extension of an external resource of kind `ad_account`.
- id
- organization_id
- external_resource_id
- provider
- external_account_id
- name
- currency
- timezone
- status
- created_at
- updated_at

Unique:
- organization_id + provider + external_account_id

## 9. Campaign Structure

### campaigns
- id
- organization_id
- ad_account_id
- provider
- external_campaign_id
- name
- objective
- status
- daily_budget
- currency
- start_at
- end_at
- created_at
- updated_at

### ad_groups
- id
- organization_id
- campaign_id
- external_ad_group_id
- name
- status
- budget
- created_at
- updated_at

### ads
- id
- organization_id
- ad_group_id
- external_ad_id
- name
- status
- creative_id
- created_at
- updated_at

### creatives
- id
- organization_id
- product_id nullable
- campaign_id nullable
- angle
- version
- headline
- description
- primary_text
- call_to_action
- asset_reference
- approval_status
- created_at
- updated_at

## 10. Keywords / Targeting

### keywords
- id
- organization_id
- ad_group_id
- external_keyword_id
- keyword
- match_type
- status
- created_at
- updated_at

### audience_targets
- id
- organization_id
- ad_group_id/campaign_id
- provider
- external_target_id
- target_type
- target_value
- status
- metadata JSONB

## 11. Performance Data

### ad_performance_daily
- id
- organization_id
- ad_account_id
- campaign_id
- ad_group_id nullable
- ad_id nullable
- date
- impressions
- clicks
- spend
- conversions
- conversion_value
- currency
- raw_source_reference

Unique key should prevent duplicate provider/date/entity records.

## 12. Analytics

### Analytics as built (Phase 5, migrations 0014 and 0015; decision Q11 settled by A23)

GA4's Data API returns **aggregated reports, not events**, so AdVegaX stores daily aggregates and discovers properties with the GA4 Admin API. Forced Row-Level Security and composite tenant keys on all three tables; the scheduler's system role reads four columns of `analytics_properties` only (id, organization, provider, first import time).

**analytics_properties** (extension of an `analytics_property` resource)
- id, organization_id, external_resource_id (unique), provider, external_property_id (unique per organization and provider)
- name, account_name (display only), currency, timezone
- status (`importing` | `active` | `disconnected` | `error`), platform_status (`active` | `deleted`)
- history_from, first_import_completed_at, health_code, health_checked_at, created_at, updated_at

**analytics_daily** — one row per property, day, view and value (unique)
- id, organization_id, property_id, day (property time zone)
- breakdown (`total` | `channel` | `source`), dimension_key (`total`, the channel group, or `source|medium|campaign`), channel_group, traffic_source, traffic_medium, campaign
- sessions, engaged_sessions, total_users, new_users, key_events (exact decimal), purchases, purchase_revenue (exact decimal, property currency) — NULL when not provided, never 0
- every measure is ≥ 0 except **purchase_revenue**, which is purchases minus refunds in GA4 and can be negative on a day with more refunds (migration 0015, task 5-05)
- quality flags: other_row, thresholded, sampled, truncated (shown, never hidden)
- currency, source (`platform_reported`), fetched_at
- **Users are distinct counts per day and are never added across days or views** (Q-5-5).
- `dimension_key` for the source view escapes `\` and `|` inside values. The source view keeps at most `ANALYTICS_SOURCE_ROWS_PER_DAY` values a day (500); the rest are added into one `(other)|(other)|(other)` row with `other_row` set and users unknown.

**analytics_sync_state** — as `ad_sync_state`, keyed by property_id.

### analytics_events
> **Superseded by Q11 (A23, 2026-10-19): not created.** The GA4 Data API returns aggregated reports, not events; `analytics_daily` above replaces this table. The outline is kept for reference (event-level data would need BigQuery export, out of scope).

- id
- organization_id
- store_id nullable
- event_name
- event_time
- session_id nullable
- user_reference nullable
- product_id nullable
- source
- medium
- campaign
- metadata JSONB

### funnel_daily
- id
- organization_id
- store_id
- date
- impressions
- clicks
- landing_page_views
- product_views
- add_to_carts
- checkouts
- purchases

## 13. Financial Aggregates

> Original target model, kept for reference. **As built in Phase 2A: see §4A.**

### financial_daily
- id
- organization_id
- store_id
- date
- currency
- gross_revenue
- discounts
- refunds
- net_revenue
- ad_spend
- product_cost
- shipping_cost
- payment_fees
- gross_profit
- contribution_profit
- order_count

Financial aggregates are derived by deterministic application logic. They store additive, measurable components only; ROAS, CPA, margins, profit margin and budget utilization are calculated on read (A5). Any cached derived value must be reproducible from these components.

## 14. AI Tables

### ai_models
- id
- provider
- model_name
- version
- active
- created_at

### prompt_versions
- id
- name
- version
- template
- status
- created_at

### ai_runs
- id
- organization_id
- user_id nullable
- model_id
- prompt_version_id
- task_type
- input_reference
- output_json
- status
- input_tokens
- output_tokens
- estimated_cost
- latency_ms
- created_at

### recommendations
- id
- organization_id
- ai_run_id
- recommendation_type
- title
- explanation
- confidence
- proposed_action JSONB
- status
- expires_at
- created_at
- updated_at

## 15. Action / Automation Tables

### actions
- id
- organization_id
- recommendation_id nullable
- requested_by_user_id nullable
- action_type
- provider
- resource_type
- resource_id
- payload JSONB
- status
- idempotency_key
- validation_result JSONB
- execution_result JSONB
- created_at
- executed_at

### automation_policies
- id
- organization_id
- mode
- max_daily_spend
- max_budget_increase_percent
- max_budget_decrease_percent
- min_campaign_age_hours
- min_conversions
- max_actions_per_day
- enabled
- created_at
- updated_at

## 16. Audit (Phase 1A)

### audit_logs (Phase 1A — migration 0003)
Append-only. The application role may insert and read (within its tenant) but never update or delete; no runtime role holds UPDATE, DELETE or TRUNCATE. Indexes: `(organization_id, created_at)`, `actor_user_id`. `organization_id` uses ON DELETE RESTRICT. The `metadata` column is exposed as `metadata` in the API.
- id
- organization_id nullable
- actor_type (user, system, worker, ai_recommendation)
- actor_user_id nullable
- action
- resource_type, resource_id
- result (success, denied, failed)
- correlation_id
- before_json, after_json (secrets scrubbed)
- metadata JSONB (later: approver, recommendation/action references, provider and external resource)
- created_at

Never store secrets in audit payloads.

## 17. Billing

### billing_customers
- id
- organization_id
- provider_customer_id
- status
- created_at

### subscriptions
- id
- organization_id
- provider_subscription_id
- plan
- status
- current_period_start
- current_period_end
- cancel_at_period_end
- created_at
- updated_at

### invoices
- id
- organization_id
- provider_invoice_id
- status
- amount
- currency
- due_at
- paid_at
- created_at

## 18. Notifications

### notifications
- id
- organization_id
- user_id
- type
- title
- message
- severity
- read_at
- created_at

## 19. Database Security

All tenant-owned tables have `organization_id` directly (denormalized where needed) and composite foreign keys `(organization_id, parent_id)` so cross-tenant references are impossible.

Every service query enforces organization scope. PostgreSQL Row-Level Security is **required** on every tenant-owned table as defence in depth (Decision D12). It does not replace application authorization.

**Roles**
- `advegax_migrator`: owns the schema; used only by migrations.
- `advegax_app`: runtime role; not superuser, not owner, no BYPASSRLS.
- `advegax_system`: narrow, audited operations only (e.g. enumerating due jobs, email outbox delivery, retention).
Tables use `FORCE ROW LEVEL SECURITY`. No `SECURITY DEFINER` functions without documented review.

**Context.** Each transaction sets `app.current_org_id` and `app.current_user_id` with transaction-local scope. Policies read them with `current_setting(..., true)` and fail closed (no rows) when unset.

**Table classes**

| Class | Tables (Phase 1) | Protection |
|---|---|---|
| Tenant-owned | invitations, audit_logs (org rows), and every future business table | RLS: `organization_id = app.current_org_id` |
| Membership | memberships | RLS: rows of the current organization, or the current user's own rows (to list/switch organizations) |
| Organization | organizations | RLS: current organization, or organizations where the current user has an active membership |
| Global identity | users, user_password_credentials, sessions, user_action_tokens | Not tenant-owned; access only through the identity service; never exposed via organization endpoints except through membership joins |
| Security/system | security_events, email_outbox (Phase 1A) | Insert-only for `advegax_app` (with `organization_id` NULL or the current organization); read/process only by `advegax_system` |
| Jobs | job_runs (Phase 1B) | Tenant-scoped SELECT/INSERT/UPDATE for `advegax_app`; `advegax_system` SELECT/UPDATE to claim, retry and recover; no DELETE |

**Verification.** CI fails if a table with `organization_id` lacks enabled + forced RLS and a policy. Cross-tenant tests cover every tenant-owned table and route.

## 19A. Data Availability (A10)

Values that a provider may not supply carry availability (`available`, `unavailable`, `unsupported`, `not_synchronized`) and source/provider metadata where needed. Nullable value + availability state, never 0, represent missing data.

## 20. Index Strategy

Index:
- foreign keys,
- tenant + frequently filtered fields,
- external IDs,
- timestamps used in synchronization,
- status fields when selective,
- reporting dimensions.

Avoid unnecessary indexes on high-write tables.

## 21. Retention

Define retention policies separately for:
- raw provider payloads,
- analytics events,
- audit logs,
- AI run records,
- security events.

Do not delete records merely to simplify reporting.
