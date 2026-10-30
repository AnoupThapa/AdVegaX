import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSignIn } from "@/features/auth/actions";
import { AccountNav } from "@/features/auth/AccountNav";
import { HomeGate } from "@/features/home/HomeGate";
import { Landing } from "@/features/home/Landing";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { SESSION_KEY } from "@/features/auth/session";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

describe("RequireAuth", () => {
  it("shows the page to signed-in users", () => {
    mockApi({ "GET /api/v1/auth/me": ok(testUser()) });
    renderWithProviders(
      <RequireAuth>
        <p>secret page</p>
      </RequireAuth>,
      { session: testUser() },
    );
    expect(screen.getByText("secret page")).toBeInTheDocument();
  });

  it("sends signed-out visitors to sign in and back afterwards", async () => {
    navigation.pathname = "/orgs/42/members";
    navigation.search = "tab=invites";
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    renderWithProviders(
      <RequireAuth>
        <p>secret page</p>
      </RequireAuth>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(
        "/sign-in?next=%2Forgs%2F42%2Fmembers%3Ftab%3Dinvites",
      ),
    );
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("redirects when the session ends while the page is open", async () => {
    navigation.pathname = "/account/security";
    // The session has ended on the server: /auth/me now answers 401.
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    const { queryClient } = renderWithProviders(
      <RequireAuth>
        <p>secret page</p>
      </RequireAuth>,
      { session: testUser() },
    );
    act(() => queryClient.setQueryData(SESSION_KEY, null)); // what a 401 does
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in?next=%2Faccount%2Fsecurity"),
    );
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("shows an error instead of redirecting when the API is unreachable", async () => {
    mockApi({ "GET /api/v1/auth/me": fail(503, "SERVICE_UNAVAILABLE") });
    renderWithProviders(
      <RequireAuth>
        <p>secret page</p>
      </RequireAuth>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily unavailable");
    expect(router.replace).not.toHaveBeenCalled();
  });
});

describe("Account navigation", () => {
  it("offers sign-in and sign-up when signed out", () => {
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    renderWithProviders(<AccountNav />, { session: null });
    const nav = screen.getByRole("navigation", { name: "Account" });
    expect(nav).toHaveTextContent("Sign in");
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/sign-up",
    );
  });

  it("opens the account menu with the person's name and email, and closes it with Escape", () => {
    mockApi({ "GET /api/v1/auth/me": ok(testUser()) });
    renderWithProviders(<AccountNav />, { session: testUser() });
    const toggle = screen.getByRole("button", { name: /account menu/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Account security" })).toBeNull();
    click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Account security" })).toHaveAttribute(
      "href",
      "/account/security",
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("renders nothing while the session is loading", () => {
    mockApi({ "GET /api/v1/auth/me": () => new Promise<Response>(() => {}) });
    const { container } = renderWithProviders(<AccountNav />);
    expect(container).toBeEmptyDOMElement();
  });

  it("signs out: calls the API, clears local data and goes to sign-in", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": ok(testUser()),
      "POST /api/v1/auth/logout": ok({ status: "signed_out", csrf_token: "anon" }),
    });
    const { queryClient } = renderWithProviders(<AccountNav />, { session: testUser() });
    queryClient.setQueryData(["organizations"], [{ id: "o1" }]);
    expect(screen.getByRole("button", { name: /Ada/ })).toBeInTheDocument();
    click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/sign-in"));
    expect(api.calls.some((c) => c.path === "/api/v1/auth/logout" && c.csrf)).toBe(true);
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();
    expect(queryClient.getQueryData(["organizations"])).toBeUndefined();
  });

  it("after a deliberate sign-out, an open protected page goes to a plain sign-in page", async () => {
    navigation.pathname = "/orgs/42/connections";
    mockApi({
      "GET /api/v1/auth/me": ok(testUser()),
      "POST /api/v1/auth/logout": ok({ status: "signed_out", csrf_token: "anon" }),
    });
    renderWithProviders(
      <>
        <AccountNav />
        <RequireAuth>
          <p>secret page</p>
        </RequireAuth>
      </>,
      { session: testUser() },
    );
    click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/sign-in"));
    expect(router.replace).not.toHaveBeenCalledWith(expect.stringContaining("next="));
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("a later session loss (not a sign-out) still offers to come back", async () => {
    navigation.pathname = "/orgs/42/members";
    mockApi({
      "GET /api/v1/auth/me": ok(testUser()),
      "POST /api/v1/auth/logout": ok({ status: "signed_out", csrf_token: "anon" }),
      "POST /api/v1/auth/login": ok({ status: "signed_in", csrf_token: "t" }),
    });
    // Sign out on a public page (no protected page consumes the flag) …
    const first = renderWithProviders(<AccountNav />, { session: testUser() });
    click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/sign-in"));
    first.unmount();
    // … then sign in again: the flag is cleared, so a later 401 keeps the return address.
    function SignInProbe() {
      const signIn = useSignIn();
      return (
        <button onClick={() => signIn.mutate({ email: "ada@example.com", password: "x" })}>
          go
        </button>
      );
    }
    const probe = renderWithProviders(<SignInProbe />);
    click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(probe.queryClient.getQueryData(SESSION_KEY)).toEqual(testUser()));
    probe.unmount();
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    renderWithProviders(
      <RequireAuth>
        <p>secret page</p>
      </RequireAuth>,
    );
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/sign-in?next=%2Forgs%2F42%2Fmembers"),
    );
  });

  it("still clears local data if the sign-out request fails", async () => {
    mockApi({
      "GET /api/v1/auth/me": ok(testUser()),
      "POST /api/v1/auth/logout": fail(503, "SERVICE_UNAVAILABLE"),
    });
    const { queryClient } = renderWithProviders(<AccountNav />, { session: testUser() });
    click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/sign-in"));
    expect(queryClient.getQueryData(SESSION_KEY)).toBeNull();
  });
});

describe("Home page session area", () => {
  it("invites signed-out visitors to start", () => {
    mockApi({ "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED") });
    renderWithProviders(<HomeGate landing={<Landing />} />, { session: null });
    expect(screen.getAllByRole("link", { name: "Create an account" }).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { level: 1, name: /Know what your advertising/ }),
    ).toBeVisible();
  });

  it("asks unverified users to verify before creating organizations", () => {
    const user = testUser({ email_verified: false, display_name: null });
    mockApi({ "GET /api/v1/auth/me": ok(user) });
    renderWithProviders(<HomeGate landing={<Landing />} />, { session: user });
    // Shown as the signed-in name (no display name) and in the verification notice.
    expect(
      screen.getByRole("heading", { name: "Welcome back, ada@example.com" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/ada@example\.com/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("heading", { name: "Verify your email address" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send a new verification link" }),
    ).toBeInTheDocument();
  });

  it("shows nothing extra to verified users", () => {
    mockApi({ "GET /api/v1/auth/me": ok(testUser()) });
    renderWithProviders(<HomeGate landing={<Landing />} />, { session: testUser() });
    expect(screen.getByRole("heading", { name: "Welcome back, Ada" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Verify your email address" })).toBeNull();
  });
});
