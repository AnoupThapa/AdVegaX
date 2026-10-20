import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeSession } from "@/features/auth/HomeSession";
import { CreateOrganizationForm } from "@/features/organizations/CreateOrganizationForm";
import { OrganizationOverview } from "@/features/organizations/OrganizationOverview";
import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";
import {
  OrganizationShell,
  useCurrentOrganization,
} from "@/features/organizations/OrganizationShell";
import { OrganizationSwitcher } from "@/features/organizations/OrganizationSwitcher";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

function inShell(ui: React.ReactElement, path = `/orgs/${ORG_ID}`) {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = path;
  return <OrganizationShell>{ui}</OrganizationShell>;
}

describe("Create organization", () => {
  it("checks the form locally and focuses the first problem", () => {
    const api = mockApi({});
    renderWithProviders(<CreateOrganizationForm />, { session: testUser() });
    click(screen.getByRole("button", { name: "Create organization" }));
    expect(screen.getByLabelText("Organization name")).toHaveFocus();
    expect(screen.getByLabelText("Organization name")).toHaveAccessibleDescription(
      "Enter a name for the organization.",
    );
    expect(screen.getByLabelText("Reporting currency")).toHaveAccessibleDescription(
      expect.stringContaining("Choose a currency."),
    );
    expect(api.calls.filter((c) => c.path.startsWith("/api/v1/organizations"))).toEqual([]);
  });

  it("defaults the time zone to the browser's", () => {
    mockApi({});
    renderWithProviders(<CreateOrganizationForm />, { session: testUser() });
    expect(screen.getByLabelText("Time zone")).toHaveValue(
      Intl.DateTimeFormat().resolvedOptions().timeZone,
    );
  });

  it("creates the organization and opens it", async () => {
    const api = mockApi({
      "POST /api/v1/organizations": ok(testOrg(), 201),
      "GET /api/v1/auth/me": ok(testUser()),
    });
    renderWithProviders(<CreateOrganizationForm />, { session: testUser() });
    fill(screen.getByLabelText("Organization name"), "  Eve Zone  ");
    fill(screen.getByLabelText("Reporting currency"), "AUD");
    fill(screen.getByLabelText("Time zone"), "Australia/Sydney");
    click(screen.getByRole("button", { name: "Create organization" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}`));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
      name: "Eve Zone",
      default_currency: "AUD",
      default_timezone: "Australia/Sydney",
    });
  });

  it("puts API validation problems on the right field", async () => {
    mockApi({
      "POST /api/v1/organizations": fail(422, "VALIDATION_ERROR", [
        { location: ["body", "default_timezone"], message: "bad", type: "value_error" },
      ]),
    });
    renderWithProviders(<CreateOrganizationForm />, { session: testUser() });
    fill(screen.getByLabelText("Organization name"), "Eve Zone");
    fill(screen.getByLabelText("Reporting currency"), "AUD");
    fill(screen.getByLabelText("Time zone"), "Australia/Sydney");
    click(screen.getByRole("button", { name: "Create organization" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please check the form");
    expect(screen.getByLabelText("Time zone")).toHaveFocus();
    expect(screen.getByLabelText("Time zone")).toHaveAccessibleDescription(
      expect.stringContaining("Check this field and try again."),
    );
  });

  it("asks unverified users to verify first", () => {
    mockApi({});
    renderWithProviders(<CreateOrganizationForm />, {
      session: testUser({ email_verified: false }),
    });
    expect(screen.getByText(/verify your email before you can create/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Organization name")).not.toBeInTheDocument();
  });
});

describe("Organization shell", () => {
  it("loads the organization, marks the current section and focuses the heading", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg({ role: "viewer" })) });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    const heading = await screen.findByRole("heading", { level: 1, name: "Eve Zone" });
    expect(heading).toHaveFocus();
    const nav = screen.getByRole("navigation", { name: "Organization" });
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Members" })).not.toHaveAttribute("aria-current");
    expect(screen.getByText("Viewer")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View members" })).toBeInTheDocument();
  });

  it("shows owners the manage link", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg()), ...emptyOrganizationData() });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    expect(await screen.findByRole("heading", { name: "Nothing connected yet" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Manage members" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/members`,
    );
    expect(screen.getByRole("link", { name: "See connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
    expect(screen.queryByText(/Connecting platforms becomes available/)).not.toBeInTheDocument();
  });

  it("shows 'not found' for organizations the API does not reveal (404)", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: fail(404, "NOT_FOUND") });
    renderWithProviders(inShell(<p>secret</p>), { session: testUser() });
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("never sends a malformed organization ID to the API", () => {
    const api = mockApi({});
    navigation.params = { organizationId: "../admin" };
    renderWithProviders(
      <OrganizationShell>
        <p>secret</p>
      </OrganizationShell>,
      { session: testUser() },
    );
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path.startsWith("/api/v1/organizations"))).toEqual([]);
  });

  it("shows other errors with a support reference", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: fail(500, "INTERNAL_ERROR") });
    renderWithProviders(inShell(<p>x</p>), { session: testUser() });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong on our side");
    expect(alert).toHaveTextContent("Reference: req-err");
  });

  it("sends signed-out visitors to sign in", async () => {
    mockApi({});
    renderWithProviders(inShell(<p>x</p>), { session: null });
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(
        `/sign-in?next=${encodeURIComponent(`/orgs/${ORG_ID}`)}`,
      ),
    );
  });

  it("refuses to be used outside the shell", () => {
    function Orphan() {
      useCurrentOrganization();
      return null;
    }
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => renderWithProviders(<Orphan />)).toThrow(/inside OrganizationShell/);
  });
});

describe("Organization settings", () => {
  it("saves only what changed", async () => {
    const api = mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      [`PATCH ${ORG_PATH}`]: ok(testOrg({ name: "Eve Zone AU" })),
      "GET /api/v1/auth/me": ok(testUser()),
    });
    renderWithProviders(inShell(<OrganizationSettings />, `/orgs/${ORG_ID}/settings`), {
      session: testUser(),
    });
    const name = await screen.findByLabelText("Organization name");
    expect(screen.getByLabelText("Reporting currency")).toHaveValue("AUD");
    fill(name, "Eve Zone AU ");
    click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Eve Zone AU" });
  });

  it("does not call the API when nothing changed", async () => {
    const api = mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg()) });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    click(await screen.findByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("No changes to save.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("sends a changed currency and time zone", async () => {
    const api = mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      [`PATCH ${ORG_PATH}`]: ok(testOrg({ default_currency: "NPR" })),
      "GET /api/v1/auth/me": ok(testUser()),
    });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    fill(await screen.findByLabelText("Reporting currency"), "NPR");
    fill(screen.getByLabelText("Time zone"), "Asia/Tokyo");
    click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText("Settings saved.");
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      default_currency: "NPR",
      default_timezone: "Asia/Tokyo",
    });
  });

  it("checks the name locally", async () => {
    const api = mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg()) });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    fill(await screen.findByLabelText("Organization name"), " ");
    click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByLabelText("Organization name")).toHaveFocus();
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("explains a refusal (e.g. role changed meanwhile)", async () => {
    mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg({ role: "admin" })),
      [`PATCH ${ORG_PATH}`]: fail(403, "FORBIDDEN"),
      ...emptyOrganizationData(),
    });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    fill(await screen.findByLabelText("Organization name"), "New name");
    click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You do not have permission");
  });

  it("is read-only below admin", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg({ role: "manager" })) });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    expect(await screen.findByText(/Only owners and admins can change/)).toBeInTheDocument();
    expect(screen.getByText("Australia/Sydney".replace("_", " "))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });
});

describe("Organization switcher and home list", () => {
  const user = testUser({
    memberships: [
      {
        organization_id: ORG_ID,
        organization_name: "Eve Zone",
        organization_slug: "eve-zone",
        role: "owner",
      },
      {
        organization_id: "11111111-2222-4333-8444-555555555555",
        organization_name: "Mediflex",
        organization_slug: "mediflex",
        role: "viewer",
      },
    ],
  });

  it("opens, lists organizations, and closes with Escape (focus returns)", () => {
    navigation.params = { organizationId: ORG_ID };
    renderWithProviders(<OrganizationSwitcher user={user} />);
    const toggle = screen.getByRole("button", { name: /Organization:.*Eve Zone/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "Your organizations" });
    expect(within(list).getByRole("link", { name: /Eve Zone/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(within(list).getByRole("link", { name: /Mediflex.*Viewer/ })).toHaveAttribute(
      "href",
      "/orgs/11111111-2222-4333-8444-555555555555",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("closes on a click outside or after choosing", () => {
    renderWithProviders(<OrganizationSwitcher user={user} />);
    const toggle = screen.getByRole("button", { name: /Organizations/ });
    click(toggle);
    fireEvent.keyDown(document, { key: "a" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.pointerDown(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.pointerDown(document.body);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    click(toggle);
    click(screen.getByRole("link", { name: "Create an organization" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    click(toggle);
    click(screen.getByRole("link", { name: /Mediflex/ }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("says when there are no organizations yet", () => {
    renderWithProviders(<OrganizationSwitcher user={testUser()} />);
    click(screen.getByRole("button", { name: /Organizations/ }));
    expect(screen.getByText("You are not in any organization yet.")).toBeInTheDocument();
  });

  it("is hidden for unverified users without organizations", () => {
    const { container } = renderWithProviders(
      <OrganizationSwitcher user={testUser({ email_verified: false })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lists organizations on the home page", () => {
    mockApi({});
    renderWithProviders(<HomeSession />, { session: user });
    expect(screen.getByRole("heading", { name: "Your organizations" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Mediflex/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create an organization" })).toHaveAttribute(
      "href",
      "/orgs/new",
    );
  });

  it("explains how to start when there are none, without a create link if unverified", () => {
    mockApi({});
    renderWithProviders(<HomeSession />, { session: testUser({ email_verified: false }) });
    expect(screen.getByText(/ask a colleague to invite you/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create an organization" })).not.toBeInTheDocument();
  });
});
