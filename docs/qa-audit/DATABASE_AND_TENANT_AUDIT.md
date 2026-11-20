# Database and tenant isolation audit

The schema was read from a freshly migrated database (`alembic upgrade head`, 27 migrations) through the PostgreSQL catalog, as well as from the migration files.

## Schema integrity

| Check                                | Result                                                                                                                                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Migrations apply to a clean database | Yes, here and in `test_upgrade_downgrade_upgrade`, which upgrades, downgrades to base and upgrades again                                                                               |
| Models match migrations              | `test_models_match_migrations` passes                                                                                                                                                  |
| Primary keys                         | Every table has one                                                                                                                                                                    |
| Foreign keys                         | 121. Tenant-owned children use **composite keys `(organization_id, id)`**, so a row cannot reference another tenant's row (`test_composite_keys_block_cross_tenant_references`).       |
| Unique constraints                   | 109, e.g. a partial unique index on pending invitations, and webhook ids                                                                                                               |
| Check constraints                    | 161, e.g. currency shape and `base <> quote` on FX rates                                                                                                                               |
| Money                                | `NUMERIC(20,6)` throughout. There are no `real` or `double precision` columns. Python uses `Decimal`, with ratios quantised to 6 places using banker's rounding (`metrics/engine.py`). |
| Time                                 | Every timestamp column is `timestamptz`. Reporting days are computed in the organization's IANA time zone.                                                                             |
| Deletion                             | Tenant children cascade from the organization. The audit log is append-only (`test_audit_log_is_append_only`). Retention purges run through the system role (migration 0026).          |
| Indexes on foreign keys              | Partly covered: see QA-017                                                                                                                                                             |

## Tenant isolation: every layer

| Layer                  | How isolation is enforced                                                                                                                                                 | Evidence                                                                                                                             | Result        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------- |
| Authentication context | Server session, resolved per request                                                                                                                                      | `require_principal`                                                                                                                  | Pass          |
| Membership             | `tenant_context` resolves membership or an active agency grant; the URL id is only a claim                                                                                | `app/api/deps.py`                                                                                                                    | Pass          |
| Routes                 | Every organization route is swept as a non-member and must return 404                                                                                                     | `test_every_org_route_returns_404_for_non_members`                                                                                   | Pass          |
| Nested identifiers     | Another tenant's child ids under your own organization return 404                                                                                                         | `test_foreign_child_ids_under_own_org_return_404`                                                                                    | Pass          |
| Database (RLS)         | **Forced** RLS on every tenant table. The context is set per transaction with `set_config(…, true)`, so it cannot leak through pooled connections. No role has BYPASSRLS. | `test_rls.py` (no context sees nothing; A never sees B; no cross-tenant writes or updates; no pooled leakage); catalog: 192 policies | Pass          |
| Background jobs        | The system role still has no BYPASSRLS and uses per-table policies. Jobs carry their organization id.                                                                     | `001_roles.sql`; `test_runtime_roles_are_least_privileged`                                                                           | Pass          |
| Invitations            | A token cannot be redirected to another tenant                                                                                                                            | `test_invitation_token_cannot_be_redirected_to_other_tenant`                                                                         | Pass          |
| Agency access          | Grants are scoped to one client organization, can be revoked, and are audited as "via agency"                                                                             | `tests/api/test_agency_api.py`; e2e `agency`                                                                                         | Pass          |
| Browser                | An outsider gets "not found" on another organization's pages                                                                                                              | e2e `tenant-boundary`                                                                                                                | Pass          |
| Caches and Redis       | Keys are namespaced by hashed token, user or session. No tenant data is cached in Redis.                                                                                  | Code review                                                                                                                          | Pass (review) |
| File storage           | Creative assets are stored per organization and served only through tenant routes                                                                                         | `core/storage`, creatives tests                                                                                                      | Pass (review) |
| Audit logs             | RLS-scoped to the organization; append-only                                                                                                                               | `test_rls.py`                                                                                                                        | Pass          |

**No cross-tenant access was found.** Active cross-tenant attack probing beyond the automated suite was not approved, so that part is _Not Verified_. The automated suite already covers the brief's list: read, modify, delete, reports, integrations, nested relationships and jobs.

## Tables without RLS (by design)

`users`, `user_password_credentials`, `sessions`, `user_action_tokens` (global identity), `fx_rates`, `ai_models`, `prompt_versions` (shared reference data) and `alembic_version`. `user_action_tokens` has an `organization_id` column, which the documentation says CI should reject; the test exempts it by name (QA-016).

## Foreign keys without an exactly matching index (sample)

`action_events(organization_id)`, `webhook_events(organization_id)`, `recommendation_outcomes(organization_id)`, `actions(requested_by)`, `ai_runs(user_id)` and others. Most composite keys are partly covered by an index on their more selective column. QA-017 recommends checking the retention purge and organization deletion plans on production-sized data.

## Data integrity observations

- A reporting currency is only shape-checked (QA-009).
- Concurrent duplicate invitations are prevented by the database, but they surface as 500s (QA-005). No orphan or duplicate rows were produced in any probe.
- Changes to ad platforms use row locks (`with_for_update`) and record an "unknown" outcome when the platform's answer is lost, rather than guessing (`actions/engine.py`, `builder/launch.py`). This is the correct conservative choice.
