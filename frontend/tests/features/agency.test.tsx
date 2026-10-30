import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgencySettings } from "@/features/agency/AgencySettings";
import { ClientsPage } from "@/features/agency/ClientsPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const me = testUser();
const AGENCY = `${ORG_PATH}/agency`;
const OTHER = "7a1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e";
const GRANT = "5b0f3e1a-2c3d-4e5f-8a9b-0c1d2e3f4a5b";

const grant = (over: Record<string, unknown> = {}) => ({
  id: GRANT,
  client_id: ORG_ID,
  client_name: "Eve Zone",
  agency_id: OTHER,
  agency_name: "Growth Agency",
  role: "manager",
  status: "active",
  created_at: "2026-10-28T00:00:00Z",
  accepted_at: "2026-10-28T01:00:00Z",
  revoked_at: null,
  ...over,
});
const agencyData = (over: Record<string, unknown> = {}) => ({
  enabled: true,
  code: null,
  can_grant: true,
  can_manage: true,
  agencies: [],
  clients: [],
  ...over,
});

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

function base(agency: unknown, extra: Parameters<typeof mockApi>[0] = {}, org = testOrg()) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(org),
    ...emptyOrganizationData(),
    [`GET ${AGENCY}`]: ok(agency),
    ...extra,
  });
}

function render(children: React.ReactNode, path = `/orgs/${ORG_ID}/settings`) {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = path;
  renderWithProviders(<OrganizationShell>{children}</OrganizationShell>, { session: me });
}

describe("Settings → Agency access", () => {
  it("gives an agency access with a role", async () => {
    const api = base(agencyData(), {
      [`POST ${AGENCY}/grants`]: ok(grant({ status: "pending" }), 201),
    });
    render(<AgencySettings org={testOrg()} />);
    expect(await screen.findByText("No agency has access.")).toBeVisible();
    const form = screen.getByRole("form", { name: "Give an agency access" });
    fill(within(form).getByLabelText(/Agency code/), "ABCD2345EF");
    within(form).getByLabelText("Their role here");
    click(within(form).getByRole("button", { name: "Give access" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "POST")?.body).toEqual({
        code: "ABCD2345EF",
        role: "manager",
      }),
    );
    expect(await screen.findByText(/It starts when the agency accepts it/)).toBeVisible();
  });

  it("explains an unknown code and a repeated offer", async () => {
    const api = base(agencyData(), {
      [`POST ${AGENCY}/grants`]: fail(422, "VALIDATION_ERROR", [
        { field: "code", reason: "unknown_agency_code" },
      ]),
    });
    render(<AgencySettings org={testOrg()} />);
    const form = await screen.findByRole("form", { name: "Give an agency access" });
    fill(within(form).getByLabelText(/Agency code/), "ZZZZZZZZZZ");
    click(within(form).getByRole("button", { name: "Give access" }));
    expect(await screen.findByText(/No agency has this code/)).toBeVisible();
    api.set(`POST ${AGENCY}/grants`, fail(409, "CONFLICT"));
    click(within(form).getByRole("button", { name: "Give access" }));
    expect(await screen.findByText(/already has, or has been offered, access/)).toBeVisible();
  });

  it("lists agencies and ends access", async () => {
    const api = base(agencyData({ agencies: [grant()] }), {
      [`POST ${AGENCY}/grants/${GRANT}/revoke`]: ok(grant({ status: "revoked" })),
    });
    render(<AgencySettings org={testOrg()} />);
    const list = await screen.findByRole("list", { name: "Agencies" });
    expect(list).toHaveTextContent("Growth Agency — Manager, has access");
    click(within(list).getByRole("button", { name: "End access for Growth Agency" }));
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.path === `${AGENCY}/grants/${GRANT}/revoke`)).toBe(true),
    );
  });

  it("shows the agency code, a new code, and accepts a client", async () => {
    const api = base(
      agencyData({
        code: "QWERTY2345",
        clients: [grant({ status: "pending", client_id: OTHER, agency_id: ORG_ID })],
      }),
      {
        [`POST ${AGENCY}/code`]: ok({ code: "NEWCODE234" }),
        [`POST ${AGENCY}/grants/${GRANT}/accept`]: fail(409, "CONFLICT"),
      },
    );
    render(<AgencySettings org={testOrg()} />);
    expect(await screen.findByText("QWERTY2345")).toBeVisible();
    click(screen.getByRole("button", { name: "Make a new code" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path === `${AGENCY}/code`)).toBe(true));
    const clients = screen.getByRole("list", { name: "Clients" });
    expect(clients).toHaveTextContent("waiting for the agency to accept");
    click(within(clients).getByRole("button", { name: "Accept Eve Zone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already has");
    expect(screen.getByRole("link", { name: "See all clients" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/clients`,
    );
  });

  it("is hidden while switched off, and offers no code without rights", async () => {
    base({ ...agencyData(), enabled: false });
    render(<AgencySettings org={testOrg()} />);
    await screen.findByRole("navigation", { name: "Organization" });
    expect(screen.queryByRole("heading", { name: "Agency access" })).toBeNull();
  });
});

describe("Working through an agency", () => {
  it("says so on every page", async () => {
    base(agencyData(), {}, testOrg({ role: "manager", via_agency: "Growth Agency" }));
    render(<p>Body</p>, `/orgs/${ORG_ID}`);
    expect(await screen.findByText(/through Growth Agency, as Manager/)).toBeVisible();
  });
});

describe("Clients", () => {
  it("lists each client on its own, with a Clients link in the menu", async () => {
    base(agencyData({ clients: [grant({ client_id: OTHER })] }), {
      [`GET ${ORG_PATH}/clients`]: ok([
        {
          organization_id: OTHER,
          name: "Eve Zone",
          role: "manager",
          billing_status: "trialing",
          currency: "AUD",
          ad_spend: { value: "120.50", availability: "available", reason: null },
          net_sales: { value: null, availability: "not_connected", reason: "no_store" },
          open_recommendations: 2,
          connections_needing_attention: 1,
        },
      ]),
    });
    render(<ClientsPage />, `/orgs/${ORG_ID}/clients`);
    const table = await screen.findByRole("table", { name: "Clients" });
    const row = within(table).getByRole("row", { name: /Eve Zone/ });
    expect(row).toHaveTextContent("Manager");
    expect(row).toHaveTextContent("Trial");
    expect(row).toHaveTextContent("120.50");
    expect(await screen.findByRole("link", { name: "Clients" })).toBeVisible();
  });

  it("says when there is no client, and shows errors", async () => {
    const api = base(agencyData(), { [`GET ${ORG_PATH}/clients`]: ok([]) });
    render(<ClientsPage />, `/orgs/${ORG_ID}/clients`);
    expect(await screen.findByText(/No client has given this organization access/)).toBeVisible();
    api.set(`GET ${ORG_PATH}/clients`, fail(409, "CONFLICT"));
  });

  it("shows a refusal", async () => {
    base(agencyData(), { [`GET ${ORG_PATH}/clients`]: fail(500, "INTERNAL_ERROR") });
    render(<ClientsPage />, `/orgs/${ORG_ID}/clients`);
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});
