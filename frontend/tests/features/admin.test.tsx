import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/features/admin/AdminPage";
import { AccountNav } from "@/features/auth/AccountNav";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";

const okList = (items: unknown[], total = items.length) =>
  new Response(
    JSON.stringify({
      data: items,
      meta: { request_id: "req-test", page: 1, page_size: 50, total },
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
import { resetNavigation } from "../support/navigation";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const me = testUser();
const ME = "GET /api/v1/admin/me";
const admin = (over: Record<string, boolean> = {}) => ({
  is_admin: true,
  totp_enabled: true,
  verified: true,
  ...over,
});
const setting = (over: Record<string, unknown> = {}) => ({
  name: "ANTHROPIC_API_KEY",
  label: "Anthropic API key",
  group: "AI (Anthropic)",
  kind: "secret",
  source: "default",
  set: false,
  hint: null,
  updated_at: null,
  ...over,
});
const portal = {
  "GET /api/v1/admin/settings": ok([
    setting(),
    setting({
      name: "AGENCY_ENABLED",
      label: "Agency mode",
      group: "Features",
      kind: "switch",
      hint: "off",
    }),
  ]),
  "GET /api/v1/admin/organizations": okList([
    { id: "0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b", name: "Eve Zone", status: "active" },
  ]),
  "GET /api/v1/admin/users": okList([
    {
      id: "11111111-1f2a-4c1e-9a55-3f1f0d1f2a3b",
      email: "demo@advegax.local",
      display_name: "Demo",
      status: "active",
      created_at: "2026-10-28T00:00:00Z",
      is_admin: true,
    },
  ]),
  "GET /api/v1/admin/health": ok({
    database: true,
    redis: true,
    environment: "local",
    switches: { AGENCY_ENABLED: false },
    restart_needed: false,
    organizations_total: 1,
    organizations_active: 1,
    people_total: 1,
    administrators: 1,
  }),
};

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

function render() {
  renderWithProviders(<AdminPage />, { session: me });
}

describe("Admin portal", () => {
  it("is closed to customers", async () => {
    mockApi({ "GET /api/v1/auth/me": ok(me), [ME]: ok(admin({ is_admin: false })) });
    render();
    expect(await screen.findByText(/only for the people who run/)).toBeVisible();
  });

  it("sets up two-step sign-in", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: ok(admin({ totp_enabled: false, verified: false })),
      "POST /api/v1/admin/two-step/setup": ok({ secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://x" }),
      "POST /api/v1/admin/two-step/enable": fail(422, "VALIDATION_ERROR"),
    });
    render();
    click(await screen.findByRole("button", { name: "Start" }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeVisible();
    const form = screen.getByRole("form", { name: "Switch two-step sign-in on" });
    fill(within(form).getByLabelText(/Code from your authenticator app/), "123456");
    click(within(form).getByRole("button", { name: "Switch two-step sign-in on" }));
    expect(await screen.findByText(/That code did not work/)).toBeVisible();
    expect(api.apiCalls().find((c) => c.path.endsWith("/enable"))?.body).toEqual({
      code: "123456",
    });
  });

  it("asks for the code at each sign-in", async () => {
    let verified = false;
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: () => ok(admin({ verified })),
      "POST /api/v1/admin/two-step/verify": () => {
        verified = true;
        return ok(admin());
      },
      ...portal,
    });
    render();
    const form = await screen.findByRole("form", { name: "Open the Admin portal" });
    fill(within(form).getByLabelText(/Code from your authenticator app/), "654321");
    click(within(form).getByRole("button", { name: "Open the Admin portal" }));
    expect(await screen.findByRole("heading", { name: "System health" })).toBeVisible();
    expect(api.apiCalls().some((c) => c.path.endsWith("/verify"))).toBe(true);
  });

  it("saves keys and switches, lists organizations and people", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: ok(admin()),
      ...portal,
      "PUT /api/v1/admin/settings/ANTHROPIC_API_KEY": ok([
        setting({ set: true, hint: "••••1234", source: "portal" }),
        setting({
          name: "AGENCY_ENABLED",
          label: "Agency mode",
          group: "Features",
          kind: "switch",
          hint: "off",
        }),
      ]),
      "PUT /api/v1/admin/settings/AGENCY_ENABLED": ok([setting()]),
      "PUT /api/v1/admin/organizations/0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b/status": ok({
        id: "0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b",
        name: "Eve Zone",
        status: "suspended",
      }),
    });
    render();
    click(await screen.findByRole("button", { name: "Change Anthropic API key" }));
    const form = await screen.findByRole("form", { name: "Anthropic API key" });
    fill(within(form).getByLabelText("Anthropic API key"), "sk-ant-1234");
    click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/••••1234/)).toBeVisible();
    expect(screen.getAllByText(/saved here/)[0]).toBeVisible();
    const agency = await screen.findByRole("switch", { name: "Agency mode" });
    expect(agency).toHaveAttribute("aria-checked", "false");
    click(agency);
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("AGENCY_ENABLED"))?.body).toEqual({
        value: "true",
      }),
    );
    click(screen.getByRole("button", { name: "Suspend Eve Zone" }));
    // QA-018: suspending asks first; nothing is sent until it is confirmed.
    const confirm = await screen.findByRole("dialog", { name: "Suspend Eve Zone?" });
    expect(api.apiCalls().some((c) => c.path.endsWith("/status"))).toBe(false);
    click(within(confirm).getByRole("button", { name: "Suspend" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/status"))).toBe(true));
    expect(screen.getByRole("table", { name: "People" })).toHaveTextContent("demo@advegax.local");
    expect(screen.getAllByText("OK")).toHaveLength(2);
  });

  it("shows the Admin portal link in the account menu only to administrators", async () => {
    mockApi({ "GET /api/v1/auth/me": ok(me), [ME]: ok(admin()) });
    renderWithProviders(<AccountNav />, { session: me });
    click(screen.getByRole("button", { name: /account menu/ }));
    expect(await screen.findByRole("link", { name: "Admin portal" })).toHaveAttribute(
      "href",
      "/admin",
    );
  });

  it("does not show the Admin portal link to everyone else", async () => {
    mockApi({ "GET /api/v1/auth/me": ok(me), [ME]: ok({ is_admin: false }) });
    renderWithProviders(<AccountNav />, { session: me });
    click(screen.getByRole("button", { name: /account menu/ }));
    expect(screen.getByRole("link", { name: "Account security" })).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Admin portal" })).toBeNull());
  });
});

describe("Admin portal states", () => {
  it("shows failing health, a waiting restart, switches that are on, and closes a key form", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: ok(admin()),
      ...portal,
      "GET /api/v1/admin/health": ok({
        database: false,
        redis: false,
        environment: "local",
        switches: {},
        restart_needed: true,
      }),
      "GET /api/v1/admin/settings": ok([
        setting({ set: true, hint: "", source: "settings_file" }),
        setting({
          name: "AGENCY_ENABLED",
          label: "Agency mode",
          group: "Features",
          kind: "switch",
          hint: "on",
          source: "portal",
        }),
        setting({
          name: "META_APP_ID",
          label: "App ID",
          group: "Meta",
          kind: "text",
          set: true,
          hint: "1234567",
          source: "portal",
        }),
      ]),
      "PUT /api/v1/admin/settings/AGENCY_ENABLED": fail(422, "VALIDATION_ERROR"),
      "DELETE /api/v1/admin/settings/META_APP_ID": ok([setting()]),
    });
    render();
    expect(await screen.findAllByText("Not reachable")).toHaveLength(2);
    expect(screen.getByText(/a saved change is waiting/)).toBeVisible();
    expect(screen.getByText("Set")).toBeVisible();
    const agency = screen.getByRole("switch", { name: "Agency mode" });
    expect(agency).toHaveAttribute("aria-checked", "true");
    click(agency);
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("AGENCY_ENABLED"))?.body).toEqual({
        value: "false",
      }),
    );
    expect(await screen.findByRole("alert")).toBeVisible();
    click(screen.getByRole("button", { name: "Change App ID" }));
    click(screen.getByRole("button", { name: "Close App ID" }));
    expect(screen.queryByRole("form", { name: "App ID" })).toBeNull();
    click(screen.getByRole("button", { name: "Change App ID" }));
    click(await screen.findByRole("button", { name: "Use the settings file instead" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.method === "DELETE")).toBe(true));
  });
});

describe("Admin portal tables and figures", () => {
  const ORGS = [
    { id: "0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b", name: "Eve Zone", status: "active" },
    { id: "1b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b", name: "Mediflex", status: "suspended" },
  ];
  const PEOPLE = [
    {
      id: "11111111-1f2a-4c1e-9a55-3f1f0d1f2a3b",
      email: "demo@advegax.local",
      display_name: "Demo",
      status: "active",
      created_at: "2026-10-28T00:00:00Z",
      is_admin: true,
    },
    {
      id: "22222222-1f2a-4c1e-9a55-3f1f0d1f2a3b",
      email: "sam@example.com",
      display_name: null,
      status: "pending_verification",
      created_at: "2026-10-29T00:00:00Z",
      is_admin: false,
    },
  ];

  it("shows the counts, and searches, filters, sorts and pages on the server", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: ok(admin()),
      ...portal,
      "GET /api/v1/admin/health": ok({
        database: true,
        redis: true,
        environment: "local",
        switches: {},
        restart_needed: false,
        organizations_total: 120,
        organizations_active: 119,
        people_total: 2,
        administrators: 1,
      }),
      "GET /api/v1/admin/organizations": ({ query }) => {
        const q = (query.get("q") ?? "").toLowerCase();
        const status = query.get("status");
        const items = ORGS.filter(
          (o) => o.name.toLowerCase().includes(q) && (!status || o.status === status),
        );
        return okList(items, q || status ? items.length : 120);
      },
      "GET /api/v1/admin/users": ({ query }) => {
        const q = (query.get("q") ?? "").toLowerCase();
        return okList(PEOPLE.filter((u) => u.email.includes(q)));
      },
    });
    render();
    const orgs = await screen.findByRole("table", { name: "Organizations, by name" });
    expect(within(orgs).getByText("Suspended")).toBeVisible();
    expect(screen.getByText("119 active")).toBeVisible();
    expect(screen.getByText("1 administrator")).toBeVisible();
    expect(screen.getAllByText("of 1", { selector: "span" })).toHaveLength(2);
    expect(screen.getByText("Showing 1–2 of 120")).toBeVisible();

    const pages = screen.getByRole("navigation", { name: "Organizations pages" });
    expect(within(pages).getByRole("button", { name: "Previous" })).toBeDisabled();
    click(within(pages).getByRole("button", { name: "Next" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.query.get("page") === "2")).toBe(true));

    fill(screen.getByLabelText("Find an organization"), "medi");
    await waitFor(() => expect(within(orgs).queryByText("Eve Zone")).not.toBeInTheDocument());
    expect(api.apiCalls().some((c) => c.query.get("q") === "medi")).toBe(true);
    fill(screen.getByLabelText("Find an organization"), "");
    fill(screen.getByLabelText("Status"), "suspended");
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.query.get("status") === "suspended")).toBe(true),
    );
    fill(screen.getByLabelText("Find an organization"), "eve");
    expect(await screen.findByText("No organization matches.")).toBeVisible();

    const people = screen.getByRole("table", { name: "People" });
    expect(within(people).getByText("Pending verification")).toBeVisible();
    fill(screen.getByLabelText("Order"), "email");
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.query.get("sort") === "email")).toBe(true),
    );
    fill(screen.getByLabelText("Find a person by email or name"), "nobody");
    expect(await screen.findByText("No one matches.")).toBeVisible();
  });

  it("reactivates without asking, and cancelling a suspension sends nothing", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [ME]: ok(admin()),
      ...portal,
      "GET /api/v1/admin/organizations": okList(ORGS),
      "PUT /api/v1/admin/organizations/1b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b/status": ok({
        ...ORGS[1],
        status: "active",
      }),
    });
    render();
    click(await screen.findByRole("button", { name: "Suspend Eve Zone" }));
    const confirm = await screen.findByRole("dialog", { name: "Suspend Eve Zone?" });
    click(within(confirm).getByRole("button", { name: "Cancel" }));
    click(screen.getByRole("button", { name: "Reactivate Mediflex" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("/status"))?.body).toEqual({
        status: "active",
      }),
    );
    expect(api.apiCalls().filter((c) => c.path.endsWith("/status"))).toHaveLength(1);
  });
});
