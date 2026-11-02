import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSecurityPage } from "@/features/account/AccountSecurityPage";
import { SESSION_KEY } from "@/features/auth/session";
import { clearCsrfToken, getCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const me = testUser();
const sessions = [
  {
    id: "s-old",
    created_at: "2026-10-01T09:00:00Z",
    last_used_at: "2026-10-02T09:00:00Z",
    auth_method: "password",
    user_agent_summary:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    current: false,
  },
  {
    id: "s-here",
    created_at: "2026-10-12T08:00:00Z",
    last_used_at: "2026-10-12T09:00:00Z",
    auth_method: "password",
    user_agent_summary:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    current: true,
  },
  {
    id: "s-phone",
    created_at: "2026-10-10T08:00:00Z",
    last_used_at: "2026-10-11T08:00:00Z",
    auth_method: "password",
    user_agent_summary: null,
    current: false,
  },
];

function api(extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    "GET /api/v1/auth/sessions": ok(sessions),
    ...extra,
  });
}

beforeEach(() => {
  resetNavigation();
  navigation.pathname = "/account/security";
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

describe("Account security — sessions", () => {
  it("lists sessions with this device first and no sign-out button for it", async () => {
    api();
    renderWithProviders(<AccountSecurityPage />, { session: me });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Account security" }),
    ).toHaveFocus();
    const table = await screen.findByRole("table", { name: "3 active sessions" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Chrome on macOSThis device"),
      expect.stringContaining("Unknown device"),
      expect.stringContaining("Firefox on Windows"),
    ]);
    expect(within(rows[0]!).queryByRole("button")).toBeNull();
    expect(
      within(rows[1]!).getByRole("button", { name: /^Sign out of Unknown device/ }),
    ).toBeInTheDocument();
  });

  it("signs out another device after confirmation", async () => {
    let revoked = false;
    const calls = api({
      "DELETE /api/v1/auth/sessions/s-old": () => {
        revoked = true;
        return ok({ status: "revoked" });
      },
      "GET /api/v1/auth/sessions": () =>
        ok(revoked ? sessions.filter((s) => s.id !== "s-old") : sessions),
    });
    renderWithProviders(<AccountSecurityPage />, { session: me });
    click(await screen.findByRole("button", { name: /^Sign out of Firefox on Windows/ }));
    const dialog = screen.getByRole("dialog", { name: "Sign out of this device?" });
    expect(dialog).toHaveTextContent("Firefox on Windows will need to sign in again.");
    expect(calls.calls.some((c) => c.method === "DELETE")).toBe(false);
    click(within(dialog).getByRole("button", { name: "Sign out device" }));
    expect(await screen.findByText("Signed out of Firefox on Windows.")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "2 active sessions" })).toBeInTheDocument();
    expect(
      calls.calls.filter((c) => c.method === "DELETE").map((c) => [c.path, Boolean(c.csrf)]),
    ).toEqual([["/api/v1/auth/sessions/s-old", true]]);
  });

  it("cancelling sends nothing; errors are explained", async () => {
    const calls = api({ "DELETE /api/v1/auth/sessions/s-old": fail(404, "NOT_FOUND") });
    renderWithProviders(<AccountSecurityPage />, { session: me });
    click(await screen.findByRole("button", { name: /^Sign out of Firefox on Windows/ }));
    click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(calls.calls.some((c) => c.method === "DELETE")).toBe(false);
    click(screen.getByRole("button", { name: /^Sign out of Firefox on Windows/ }));
    click(within(screen.getByRole("dialog")).getByRole("button", { name: "Sign out device" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "does not exist, or you do not have access",
    );
  });

  it("signs out everywhere: confirms with the number of other sessions, then goes to sign-in and back", async () => {
    const calls = api({
      "POST /api/v1/auth/logout-all": ok({ status: "signed_out", csrf_token: "anon" }),
    });
    const { queryClient } = renderWithProviders(<AccountSecurityPage />, { session: me });
    await screen.findByRole("table");
    click(screen.getByRole("button", { name: "Sign out everywhere" }));
    const dialog = screen.getByRole("dialog", { name: "Sign out everywhere?" });
    expect(dialog).toHaveTextContent("This signs out this device and 2 other sessions.");
    click(within(dialog).getByRole("button", { name: "Sign out everywhere" }));
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in?next=%2Faccount%2Fsecurity"),
    );
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();
    expect(calls.calls.some((c) => c.path === "/api/v1/auth/logout-all" && c.csrf)).toBe(true);
  });

  it("explains a failed sign-out-everywhere and keeps the person signed in", async () => {
    api({ "POST /api/v1/auth/logout-all": fail(503, "SERVICE_UNAVAILABLE") });
    const { queryClient } = renderWithProviders(<AccountSecurityPage />, { session: me });
    await screen.findByRole("table");
    click(screen.getByRole("button", { name: "Sign out everywhere" }));
    click(within(screen.getByRole("dialog")).getByRole("button", { name: "Sign out everywhere" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(me);
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("sends signed-out visitors to sign in", async () => {
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    renderWithProviders(<AccountSecurityPage />);
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in?next=%2Faccount%2Fsecurity"),
    );
  });

  it("shows a loading state and API errors for the session list", async () => {
    mockApi({
      "GET /api/v1/auth/me": ok(me),
      "GET /api/v1/auth/sessions": fail(503, "SERVICE_UNAVAILABLE"),
    });
    renderWithProviders(<AccountSecurityPage />, { session: me });
    expect(screen.getByRole("status")).toHaveTextContent("Loading your sessions");
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
  });
});

describe("Account security — change password", () => {
  async function openForm(extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}) {
    const calls = api(extra);
    const rendered = renderWithProviders(<AccountSecurityPage />, { session: me });
    await screen.findByRole("table");
    return { calls, ...rendered };
  }

  it("checks the fields locally before calling the API", async () => {
    const { calls } = await openForm();
    fill(screen.getByLabelText("New password"), "ada@example.com");
    fill(screen.getByLabelText("Confirm new password"), "different");
    click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByLabelText("Current password")).toHaveFocus();
    expect(screen.getByLabelText("Current password")).toHaveAccessibleDescription(
      "Enter your current password.",
    );
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      expect.stringContaining("must not be your email address"),
    );
    expect(screen.getByLabelText("Confirm new password")).toHaveAccessibleDescription(
      "The passwords do not match.",
    );
    fill(screen.getByLabelText("Current password"), "correct horse battery staple");
    fill(screen.getByLabelText("New password"), "correct horse battery staple");
    fill(screen.getByLabelText("Confirm new password"), "correct horse battery staple");
    click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      expect.stringContaining("different from your current one"),
    );
    expect(calls.calls.some((c) => c.path === "/api/v1/auth/change-password")).toBe(false);
  });

  it("changes the password, keeps this browser signed in with the new token and clears the form", async () => {
    const { calls, queryClient } = await openForm({
      "POST /api/v1/auth/change-password": ok({
        status: "changed",
        csrf_token: "new-session-token",
      }),
    });
    fill(screen.getByLabelText("Current password"), "correct horse battery staple");
    fill(screen.getByLabelText("New password"), "a brand new passphrase 2026");
    fill(screen.getByLabelText("Confirm new password"), "a brand new passphrase 2026");
    click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(/Your password has been changed/)).toBeInTheDocument();
    expect(calls.calls.find((c) => c.path === "/api/v1/auth/change-password")?.body).toEqual({
      current_password: "correct horse battery staple",
      new_password: "a brand new passphrase 2026",
    });
    expect(getCsrfToken()).toBe("new-session-token");
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(me);
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("a wrong current password is shown on that field and does NOT sign the person out", async () => {
    const { queryClient } = await openForm({
      "POST /api/v1/auth/change-password": fail(401, "INVALID_CREDENTIALS"),
    });
    fill(screen.getByLabelText("Current password"), "not my password");
    fill(screen.getByLabelText("New password"), "a brand new passphrase 2026");
    fill(screen.getByLabelText("Confirm new password"), "a brand new passphrase 2026");
    click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your current password is incorrect.",
    );
    expect(screen.getByLabelText("Current password")).toHaveFocus();
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(me);
    await new Promise((r) => setTimeout(r, 50));
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows the API's password-policy message on the new-password field", async () => {
    await openForm({
      "POST /api/v1/auth/change-password": fail(422, "VALIDATION_ERROR", [
        {
          location: ["body", "password"],
          message: "Password must be at least 16 characters.",
          type: "password_policy",
        },
      ]),
    });
    fill(screen.getByLabelText("Current password"), "correct horse battery staple");
    fill(screen.getByLabelText("New password"), "fourteen chars");
    fill(screen.getByLabelText("Confirm new password"), "fourteen chars");
    click(screen.getByRole("button", { name: "Change password" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      expect.stringContaining("Password must be at least 16 characters."),
    );
    expect(screen.getByLabelText("New password")).toHaveFocus();
  });

  it("explains rate limiting", async () => {
    await openForm({ "POST /api/v1/auth/change-password": fail(429, "RATE_LIMITED") });
    fill(screen.getByLabelText("Current password"), "correct horse battery staple");
    fill(screen.getByLabelText("New password"), "a brand new passphrase 2026");
    fill(screen.getByLabelText("Confirm new password"), "a brand new passphrase 2026");
    click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
  });
});
