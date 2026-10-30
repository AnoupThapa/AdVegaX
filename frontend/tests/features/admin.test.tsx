import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPage } from "@/features/admin/AdminPage";
import { AccountNav } from "@/features/auth/AccountNav";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
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
  "GET /api/v1/admin/organizations": ok([
    { id: "0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b", name: "Eve Zone", status: "active" },
  ]),
  "GET /api/v1/admin/users": ok([
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
    const form = await screen.findByRole("form", { name: "Anthropic API key" });
    fill(within(form).getByLabelText("Anthropic API key"), "sk-ant-1234");
    click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/••••1234/)).toBeVisible();
    expect(screen.getByText(/saved here/)).toBeVisible();
    click(await screen.findByRole("button", { name: "Switch on: Agency mode" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("AGENCY_ENABLED"))?.body).toEqual({
        value: "true",
      }),
    );
    click(screen.getByRole("button", { name: "Suspend Eve Zone" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/status"))).toBe(true));
    expect(screen.getByRole("table", { name: "People" })).toHaveTextContent("demo@advegax.local");
    expect(screen.getAllByText("OK", { selector: "dd" })).toHaveLength(2);
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
