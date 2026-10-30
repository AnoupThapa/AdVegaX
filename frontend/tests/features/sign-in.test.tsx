import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SignInForm } from "@/features/auth/SignInForm";
import { SESSION_KEY } from "@/features/auth/session";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

describe("Sign in", () => {
  it("checks the form before calling the API and focuses the first problem", async () => {
    const api = mockApi({});
    renderWithProviders(<SignInForm />, { session: null });
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toHaveFocus();
    click(screen.getByRole("button", { name: "Sign in" }));
    const email = screen.getByLabelText("Email");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("Enter your email address.");
    expect(email).toHaveFocus();
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription("Enter your password.");
    expect(api.apiCalls().filter((c) => c.method !== "GET")).toEqual([]); // nothing submitted
  });

  it("signs in, loads the session and goes to a safe `next` page", async () => {
    navigation.search = "next=%2Forgs%2F42%3Ftab%3Dmembers";
    const me = testUser();
    const api = mockApi({
      "POST /api/v1/auth/login": ok({ user: me, csrf_token: "session-token" }),
      "GET /api/v1/auth/me": ok(me),
    });
    const { queryClient } = renderWithProviders(<SignInForm />, { session: null });
    fill(screen.getByLabelText("Email"), "  ada@example.com ");
    fill(screen.getByLabelText("Password"), "correct horse battery staple");
    click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/orgs/42?tab=members"));
    const login = api.calls.find((c) => c.path === "/api/v1/auth/login");
    expect(login?.body).toEqual({
      email: "ada@example.com",
      password: "correct horse battery staple",
    });
    expect(login?.csrf).toBe("csrf-test");
    expect(queryClient.getQueryData(SESSION_KEY)).toEqual(me);
  });

  it("ignores an unsafe `next` and goes home", async () => {
    navigation.search = "next=https%3A%2F%2Fevil.example%2F";
    renderWithProviders(<SignInForm />, { session: testUser() });
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  it("shows one generic message for wrong credentials, without server wording", async () => {
    mockApi({ "POST /api/v1/auth/login": fail(401, "INVALID_CREDENTIALS") });
    renderWithProviders(<SignInForm />, { session: null });
    fill(screen.getByLabelText("Email"), "ada@example.com");
    fill(screen.getByLabelText("Password"), "wrong password!!");
    click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The email or password is incorrect.");
    expect(alert).toHaveTextContent("Reference: req-err");
    expect(alert).not.toHaveTextContent("server text");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("explains rate limiting", async () => {
    mockApi({ "POST /api/v1/auth/login": fail(429, "RATE_LIMITED") });
    renderWithProviders(<SignInForm />, { session: null });
    fill(screen.getByLabelText("Email"), "ada@example.com");
    fill(screen.getByLabelText("Password"), "x");
    click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
  });

  it("links to sign-up and password reset", () => {
    mockApi({});
    renderWithProviders(<SignInForm />, { session: null });
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute(
      "href",
      "/sign-up",
    );
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});
