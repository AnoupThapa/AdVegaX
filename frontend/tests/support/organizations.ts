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

/** The routes the Overview and Settings read, with nothing connected. */
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
  };
}
