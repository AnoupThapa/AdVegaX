import type { Invitation, Member, Organization } from "@/features/organizations/api";

export const ORG_ID = "0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b";
export const ORG_PATH = `/api/v1/organizations/${ORG_ID}`;

export function testOrg(overrides: Partial<Organization> = {}): Organization {
  return {
    id: ORG_ID,
    name: "Eve Zone",
    slug: "eve-zone",
    default_currency: "AUD",
    default_timezone: "Australia/Sydney",
    status: "active",
    role: "owner",
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function testMember(overrides: Partial<Member> = {}): Member {
  return {
    id: "m-1",
    user_id: "user-1",
    email: "ada@example.com",
    display_name: "Ada",
    role: "owner",
    status: "active",
    created_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function testInvitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: "inv-1",
    email: "bob@example.com",
    role: "manager",
    status: "pending",
    expires_at: "2026-10-15T00:00:00Z",
    created_at: "2026-10-08T00:00:00Z",
    ...overrides,
  };
}

/** An answer of the unified analytics API with nothing connected (6-07). */
export function emptyOverview(overrides: Record<string, unknown> = {}) {
  return {
    definition_version: "analytics-v1",
    reporting_currency: "AUD",
    currency_minor_units: 2,
    reporting_timezone: "Australia/Sydney",
    store_id: null,
    from_day: "2026-09-15",
    to_day: "2026-10-14",
    sources: [],
    conversions: [],
    notes: [],
    totals: {},
    days: [],
    definitions: [],
    ...overrides,
  };
}

/** The AI planner's use with no runs yet and no price set (8-06). */
export function emptyAiUsage() {
  const period = {
    runs: 0,
    succeeded: 0,
    rejected: 0,
    failed: 0,
    input_tokens: 0,
    output_tokens: 0,
    estimated_cost_usd: null,
  };
  return {
    daily_limit: 20,
    runs_today: 0,
    remaining_today: 20,
    ai_enabled: false,
    today: period,
    last_30_days: period,
  };
}

/** The routes the Overview and Settings read, with nothing connected. */
/** The Action Engine's settings as a new organization has them (Phase 10A). */
export function emptyActionSettings(extra: Record<string, unknown> = {}) {
  return {
    engine_enabled: true,
    paused: false,
    require_second_person: false,
    max_daily_budget: null,
    currency: "AUD",
    currency_minor_units: 2,
    increase_percent: 50,
    decrease_percent: 90,
    budget_change_interval_minutes: 60,
    daily_limit_per_account: 50,
    landing_domains: [],
    updated_at: null,
    ...extra,
  };
}

export function emptyAutopilot(extra: Record<string, unknown> = {}) {
  const limits = {
    max_changes_per_day: 5,
    campaign_cooldown_days: 7,
    max_decrease_percent: 20,
    max_cumulative_decrease_percent: 50,
    cumulative_window_days: 30,
    min_campaign_age_days: 14,
  };
  return {
    enabled: false,
    enabled_by: null,
    enabled_at: null,
    stopped_by: null,
    stopped_at: null,
    stopped_reason: null,
    kinds: ["spend_without_results", "losing_money"],
    ad_account_ids: [],
    excluded_campaign_ids: [],
    ...limits,
    ceilings: limits,
    readiness: {
      ready: false,
      missing: ["installation_off", "not_in_rollout", "too_few_verified_changes"],
      verified_changes: 0,
      needed_changes: 5,
    },
    updated_at: null,
    ...extra,
  };
}

export function emptyOrganizationData(): Record<string, Response> {
  const wrap = (data: unknown) =>
    new Response(JSON.stringify({ data, meta: { request_id: "req-test" } }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  return {
    [`GET ${ORG_PATH}/stores`]: wrap([]),
    [`GET ${ORG_PATH}/ad-accounts`]: wrap([]),
    [`GET ${ORG_PATH}/analytics-properties`]: wrap([]),
    [`GET ${ORG_PATH}/analytics/overview`]: wrap(emptyOverview()),
    [`GET ${ORG_PATH}/ai/usage`]: wrap(emptyAiUsage()),
    [`GET ${ORG_PATH}/actions`]: wrap([]),
    [`GET ${ORG_PATH}/action-settings`]: wrap(emptyActionSettings()),
    [`GET ${ORG_PATH}/recommendations`]: wrap({
      summary: { enabled: true, open: 0, last_run: null, refreshes_left: 3 },
      items: [],
    }),
    [`GET ${ORG_PATH}/autopilot`]: wrap(emptyAutopilot()),
    [`GET ${ORG_PATH}/autopilot/runs`]: wrap([]),
    [`GET ${ORG_PATH}/billing`]: wrap(emptyBilling()),
    [`GET ${ORG_PATH}/optimization-settings`]: wrap({
      enabled: true,
      currency: "AUD",
      min_spend: "50.00",
      min_conversions: 5,
      budget_step_percent: 20,
      cost_jump_percent: 30,
      max_step_percent: 50,
      updated_at: null,
    }),
    [`GET ${ORG_PATH}/creative-rules`]: wrap({
      prohibited_terms: [],
      allowed_caps: [],
      base_prohibited_terms: ["cure", "100% effective", "tga approved"],
      updated_at: null,
    }),
  };
}

/** Billing switched off (the default installation): no limits, nothing to show. */
export function emptyBilling(overrides: Record<string, unknown> = {}) {
  return {
    enabled: false,
    status: "off",
    read_only: false,
    plan: null,
    subscribed_plan: null,
    interval: null,
    subscription_status: "none",
    trial_ends_at: null,
    current_period_end: null,
    cancel_at_period_end: false,
    grace_ends_at: null,
    usage: { stores: 0, ad_accounts: 0, members: 1, ai_runs_today: 0 },
    can_manage: true,
    checkout_available: false,
    portal_available: false,
    ...overrides,
  };
}
