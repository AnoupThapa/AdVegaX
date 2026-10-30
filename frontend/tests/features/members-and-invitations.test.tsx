import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptInvitation } from "@/features/organizations/AcceptInvitation";
import {
  forgetInvitationToken,
  pendingInvitationToken,
  rememberInvitationToken,
} from "@/features/organizations/invitation-token";
import { MembersPage } from "@/features/organizations/MembersPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { ORG_ID, ORG_PATH, testInvitation, testMember, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const TOKEN = "inv_abcdefghijklmnopqrst";

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
  forgetInvitationToken();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const ada = testMember();
const bob = testMember({
  id: "m-2",
  user_id: "user-2",
  email: "bob@example.com",
  display_name: null,
  role: "manager",
});
const olga = testMember({
  id: "m-3",
  user_id: "user-3",
  email: "olga@example.com",
  display_name: "Olga",
  role: "owner",
  status: "suspended",
});

function membersPage(role = "owner", extra: Record<string, ReturnType<typeof ok>> = {}) {
  const api = mockApi({
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    [`GET ${ORG_PATH}/members`]: ok([ada, bob, olga]),
    [`GET ${ORG_PATH}/invitations`]: ok([
      testInvitation(),
      testInvitation({ id: "inv-2", email: "zed@example.com", status: "revoked" }),
    ]),
    "GET /api/v1/auth/me": ok(testUser()),
    ...extra,
  });
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = `/orgs/${ORG_ID}/members`;
  const view = renderWithProviders(
    <OrganizationShell>
      <MembersPage />
    </OrganizationShell>,
    { session: testUser() },
  );
  return { api, ...view };
}

describe("Members", () => {
  it("lists members with names, roles and status", async () => {
    membersPage();
    const table = await screen.findByRole("table", { name: "3 members" });
    expect(within(table).getByText("Ada (you)")).toBeInTheDocument();
    expect(within(table).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(table).getByText("Suspended")).toBeInTheDocument();
    // The table sits in a focusable, labelled region so it can be scrolled by keyboard.
    expect(screen.getByRole("region", { name: "3 members" })).toHaveAttribute("tabindex", "0");
  });

  it("is read-only below admin (no role controls, no invitations)", async () => {
    const { api } = membersPage("manager");
    await screen.findByRole("table", { name: "3 members" });
    expect(screen.getByText(/Only owners and admins can invite/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Invitations" })).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("/invitations"))).toBe(false);
  });

  it("does not let admins change owners, and offers only roles up to their own", async () => {
    membersPage("admin");
    await screen.findByRole("table", { name: "3 members" });
    expect(screen.queryByLabelText("Role for Ada")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Olga" })).not.toBeInTheDocument();
    const options = within(screen.getByLabelText("Role for bob@example.com"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Admin", "Manager", "Analyst", "Viewer"]);
  });

  it("changes a role after an explicit save", async () => {
    const { api } = membersPage("owner", {
      [`PATCH ${ORG_PATH}/members/m-2`]: ok({ ...bob, role: "analyst" }),
    });
    const select = await screen.findByLabelText("Role for bob@example.com");
    expect(screen.queryByRole("button", { name: /Save role/ })).not.toBeInTheDocument();
    fill(select, "analyst");
    click(screen.getByRole("button", { name: "Save role for bob@example.com" }));
    expect(await screen.findByText("bob@example.com is now Analyst.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ role: "analyst" });
  });

  it("puts the role back and explains when the API refuses", async () => {
    membersPage("owner", {
      [`PATCH ${ORG_PATH}/members/m-1`]: fail(409, "LAST_OWNER"),
    });
    fill(await screen.findByLabelText("Role for Ada"), "admin");
    click(screen.getByRole("button", { name: "Save role for Ada" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least one owner");
    expect(screen.getByLabelText("Role for Ada")).toHaveValue("owner");
  });

  it("removes a member after confirmation; Cancel does nothing", async () => {
    const { api } = membersPage("owner", {
      [`DELETE ${ORG_PATH}/members/m-2`]: ok({ status: "removed" }),
    });
    click(await screen.findByRole("button", { name: "Remove bob@example.com" }));
    const dialog = screen.getByRole("dialog", { name: "Remove this member?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);

    click(screen.getByRole("button", { name: "Remove bob@example.com" }));
    fireEvent(
      screen.getByRole("dialog"),
      new Event("cancel", { cancelable: true }), // Escape
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    click(screen.getByRole("button", { name: "Remove bob@example.com" }));
    click(screen.getByRole("button", { name: "Remove member" }));
    expect(
      await screen.findByText("bob@example.com was removed from the organization."),
    ).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE" && c.path.endsWith("/m-2"))).toBe(true);
  });

  it("leaving the organization goes home", async () => {
    membersPage("owner", {
      [`DELETE ${ORG_PATH}/members/m-1`]: ok({ status: "removed" }),
    });
    click(await screen.findByRole("button", { name: "Leave organization" }));
    const dialog = screen.getByRole("dialog", { name: "Leave this organization?" });
    expect(dialog).toHaveTextContent("You will lose access");
    click(within(dialog).getByRole("button", { name: "Leave organization" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/"));
  });

  it("explains a refused removal", async () => {
    membersPage("owner", {
      [`DELETE ${ORG_PATH}/members/m-1`]: fail(409, "LAST_OWNER"),
    });
    click(await screen.findByRole("button", { name: "Leave organization" }));
    click(within(screen.getByRole("dialog")).getByRole("button", { name: "Leave organization" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least one owner");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a load error", async () => {
    mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg({ role: "viewer" })),
      [`GET ${ORG_PATH}/members`]: fail(503, "SERVICE_UNAVAILABLE"),
    });
    navigation.params = { organizationId: ORG_ID };
    renderWithProviders(
      <OrganizationShell>
        <MembersPage />
      </OrganizationShell>,
      { session: testUser() },
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  });
});

describe("Invitations", () => {
  it("lists invitations; only pending ones can be revoked", async () => {
    membersPage();
    const table = await screen.findByRole("table", { name: "Sent invitations" });
    expect(within(table).getByText("Waiting for reply")).toBeInTheDocument();
    expect(within(table).getByText("Revoked")).toBeInTheDocument();
    expect(within(table).getAllByRole("button")).toHaveLength(1);
  });

  it("checks the email locally", async () => {
    const { api } = membersPage();
    click(await screen.findByRole("button", { name: "Send invitation" }));
    expect(screen.getByLabelText("Email address")).toHaveFocus();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("sends an invitation with the chosen role, then clears the form", async () => {
    const { api } = membersPage("owner", {
      [`POST ${ORG_PATH}/invitations`]: ok(testInvitation({ email: "cy@example.com" }), 201),
    });
    const role = await screen.findByLabelText("Role");
    expect(role).toHaveValue("viewer");
    expect(role).toHaveAccessibleDescription("Views data.");
    fill(screen.getByLabelText("Email address"), " cy@example.com ");
    fill(role, "admin");
    expect(role).toHaveAccessibleDescription(expect.stringContaining("Manages members"));
    click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByText(/Invitation sent to cy@example.com/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "cy@example.com",
      role: "admin",
    });
    expect(screen.getByLabelText("Email address")).toHaveValue("");
    expect(screen.getByLabelText("Role")).toHaveValue("viewer");
  });

  it("explains an existing member and a rejected address", async () => {
    const { api } = membersPage("owner", {
      [`POST ${ORG_PATH}/invitations`]: fail(409, "ALREADY_MEMBER"),
    });
    fill(await screen.findByLabelText("Email address"), "bob@example.com");
    click(screen.getByRole("button", { name: "Send invitation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already a member");

    api.set(
      `POST ${ORG_PATH}/invitations`,
      fail(422, "VALIDATION_ERROR", [{ location: ["body", "email"], message: "x", type: "x" }]),
    );
    click(screen.getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(screen.getByLabelText("Email address")).toHaveFocus());
    expect(screen.getByLabelText("Email address")).toHaveAccessibleDescription(
      "Check this field and try again.",
    );
  });

  it("revokes a pending invitation", async () => {
    const { api } = membersPage("owner", {
      [`DELETE ${ORG_PATH}/invitations/inv-1`]: ok({ status: "revoked" }),
    });
    click(await screen.findByRole("button", { name: "Revoke invitation to bob@example.com" }));
    expect(
      await screen.findByText("The invitation to bob@example.com was revoked."),
    ).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE" && c.path.endsWith("/inv-1"))).toBe(true);
  });

  it("explains a failed revoke", async () => {
    membersPage("owner", {
      [`DELETE ${ORG_PATH}/invitations/inv-1`]: fail(409, "INVITATION_NOT_PENDING"),
    });
    click(await screen.findByRole("button", { name: "Revoke invitation to bob@example.com" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer valid");
  });

  it("handles an empty list and a load error", async () => {
    const { api } = membersPage("owner", { [`GET ${ORG_PATH}/invitations`]: ok([]) });
    expect(await screen.findByText("No invitations have been sent yet.")).toBeInTheDocument();
    expect(api.calls.length).toBeGreaterThan(0);
  });

  it("shows when invitations cannot be loaded", async () => {
    membersPage("owner", { [`GET ${ORG_PATH}/invitations`]: fail(500, "INTERNAL_ERROR") });
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong on our side");
  });
});

describe("Accept invitation", () => {
  function openLink() {
    window.history.replaceState(null, "", `/invitations/accept#token=${TOKEN}`);
  }

  it("hides the token, remembers it in memory, and asks signed-out visitors to sign in", async () => {
    openLink();
    mockApi({});
    renderWithProviders(<AcceptInvitation />, { session: null });
    const signIn = await screen.findByRole("link", { name: "Sign in to accept" });
    expect(signIn).toHaveAttribute("href", "/sign-in?next=%2Finvitations%2Faccept");
    expect(window.location.href).not.toContain(TOKEN);
    expect(pendingInvitationToken()).toBe(TOKEN);
  });

  it("accepts after an explicit click and opens the organization", async () => {
    openLink();
    const api = mockApi({
      "POST /api/v1/invitations/accept": ok(testOrg({ role: "manager" })),
      "GET /api/v1/auth/me": ok(testUser()),
    });
    renderWithProviders(<AcceptInvitation />, { session: testUser(), strict: true });
    const button = await screen.findByRole("button", { name: "Accept invitation" });
    expect(api.calls.some((c) => c.path === "/api/v1/invitations/accept")).toBe(false);
    click(button);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}`));
    const posts = api.calls.filter((c) => c.path === "/api/v1/invitations/accept");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({ token: TOKEN });
    expect(pendingInvitationToken()).toBeNull();
  });

  it("uses the remembered token after a sign-in detour", async () => {
    rememberInvitationToken(TOKEN);
    const api = mockApi({
      "POST /api/v1/invitations/accept": ok(testOrg()),
      "GET /api/v1/auth/me": ok(testUser()),
    });
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    click(await screen.findByRole("button", { name: "Accept invitation" }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ token: TOKEN });
  });

  it("explains a missing token", async () => {
    mockApi({});
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    expect(await screen.findByRole("alert")).toHaveTextContent("link is incomplete");
  });

  it("asks unverified users to verify first", async () => {
    openLink();
    mockApi({});
    renderWithProviders(<AcceptInvitation />, { session: testUser({ email_verified: false }) });
    expect(
      await screen.findByText(/open the invitation link from your email again/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept invitation" })).not.toBeInTheDocument();
  });

  it("on an email mismatch, keeps the token and offers to switch account", async () => {
    openLink();
    const api = mockApi({
      "POST /api/v1/invitations/accept": fail(403, "INVITATION_EMAIL_MISMATCH"),
      "POST /api/v1/auth/logout": ok({ status: "signed_out", csrf_token: "anon" }),
    });
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    click(await screen.findByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("different email address");
    expect(screen.queryByRole("button", { name: "Accept invitation" })).not.toBeInTheDocument();
    expect(pendingInvitationToken()).toBe(TOKEN);
    click(screen.getByRole("button", { name: "Sign out and switch account" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/sign-in?next=%2Finvitations%2Faccept"),
    );
    expect(api.calls.some((c) => c.path === "/api/v1/auth/logout")).toBe(true);
  });

  it("drops a used or expired token and says what to do", async () => {
    openLink();
    mockApi({ "POST /api/v1/invitations/accept": fail(409, "INVITATION_NOT_PENDING") });
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    click(await screen.findByRole("button", { name: "Accept invitation" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("no longer valid");
    expect(alert).toHaveTextContent("Ask the person who invited you");
    expect(pendingInvitationToken()).toBeNull();
    expect(screen.getByRole("link", { name: "Go to the home page" })).toBeInTheDocument();
  });

  it("keeps the token after a temporary failure so the person can retry", async () => {
    openLink();
    mockApi({ "POST /api/v1/invitations/accept": fail(503, "SERVICE_UNAVAILABLE") });
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    click(await screen.findByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
    expect(pendingInvitationToken()).toBe(TOKEN);
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeEnabled();
  });

  it("starts afresh when another invitation link opens in the same tab", async () => {
    openLink();
    const api = mockApi({ "POST /api/v1/invitations/accept": fail(400, "INVALID_TOKEN") });
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    click(await screen.findByRole("button", { name: "Accept invitation" }));
    await screen.findByRole("alert");

    const second = "inv_zyxwvutsrqponmlkjihg";
    window.history.replaceState(null, "", `/invitations/accept#token=${second}`);
    fireEvent(window, new HashChangeEvent("hashchange"));
    const button = await screen.findByRole("button", { name: "Accept invitation" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(window.location.href).not.toContain(second);

    api.set("POST /api/v1/invitations/accept", ok(testOrg()));
    click(button);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}`));
    expect(api.calls.filter((c) => c.method === "POST").at(-1)?.body).toEqual({ token: second });
  });

  it("ignores a hash change without a token", async () => {
    openLink();
    mockApi({});
    renderWithProviders(<AcceptInvitation />, { session: testUser() });
    await screen.findByRole("button", { name: "Accept invitation" });
    window.history.replaceState(null, "", "/invitations/accept#section");
    fireEvent(window, new HashChangeEvent("hashchange"));
    expect(screen.getByRole("button", { name: "Accept invitation" })).toBeInTheDocument();
  });
});
