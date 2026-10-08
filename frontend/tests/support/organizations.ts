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
