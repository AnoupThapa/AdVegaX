import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CheckEmail } from "@/features/auth/CheckEmail";
import { SignUpForm } from "@/features/auth/SignUpForm";
import { VerifyEmail } from "@/features/auth/VerifyEmail";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { resetNavigation, router } from "../support/navigation";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("Sign up", () => {
  it("checks name, email and password locally", () => {
    const api = mockApi({});
    renderWithProviders(<SignUpForm />, { session: null });
    fill(screen.getByLabelText("Email"), "ada@example.com");
    fill(screen.getByLabelText("Password"), "ada@example.com");
    click(screen.getByRole("button", { name: "Create account" }));
    const password = screen.getByLabelText("Password");
    expect(password).toHaveFocus();
    expect(password).toHaveAccessibleDescription(
      expect.stringContaining("Your password must not be your email address."),
    );
    expect(screen.getByLabelText(/Your name/)).not.toHaveAttribute("aria-invalid");
    expect(api.apiCalls().filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("registers and shows the check-your-email page", async () => {
    const api = mockApi({ "POST /api/v1/auth/register": ok({ status: "accepted" }, 202) });
    renderWithProviders(<SignUpForm />, { session: null });
    fill(screen.getByLabelText(/Your name/), "  Ada  ");
    fill(screen.getByLabelText("Email"), "ada@example.com");
    fill(screen.getByLabelText("Password"), "correct horse battery staple");
    click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/check-email"));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "ada@example.com",
      password: "correct horse battery staple",
      display_name: "Ada",
    });
  });

  it("shows the API's password-policy message on the password field", async () => {
    mockApi({
      "POST /api/v1/auth/register": fail(422, "VALIDATION_ERROR", [
        {
          location: ["body", "password"],
          message: "Password must be at least 16 characters.",
          type: "password_policy",
        },
      ]),
    });
    renderWithProviders(<SignUpForm />, { session: null });
    fill(screen.getByLabelText("Email"), "ada@example.com");
    fill(screen.getByLabelText("Password"), "correct horse ok");
    click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please check the form");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAccessibleDescription(
      expect.stringContaining("Password must be at least 16 characters."),
    );
    expect(password).toHaveFocus();
  });

  it("check-email page gives next steps without naming the address", () => {
    renderWithProviders(<CheckEmail />);
    expect(screen.getByRole("heading", { level: 1, name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/sign-in");
  });
});

describe("Verify email", () => {
  it("sends the fragment token exactly once (even in Strict Mode) and hides it", async () => {
    window.history.replaceState(null, "", "/verify-email#token=tok_abcdefghijklmnopqrst");
    const api = mockApi({ "POST /api/v1/auth/verify-email": ok({ status: "verified" }) });
    renderWithProviders(<VerifyEmail />, { session: null, strict: true });
    expect(await screen.findByText("Your email address is verified.")).toBeInTheDocument();
    const posts = api.calls.filter((c) => c.path === "/api/v1/auth/verify-email");
    expect(posts).toHaveLength(1);
    expect(posts[0]?.body).toEqual({ token: "tok_abcdefghijklmnopqrst" });
    expect(window.location.href).not.toContain("tok_");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });

  it("explains an expired link and offers a new one to signed-in users", async () => {
    window.history.replaceState(null, "", "/verify-email#token=tok_abcdefghijklmnopqrst");
    const api = mockApi({
      "POST /api/v1/auth/verify-email": fail(400, "INVALID_TOKEN"),
      "GET /api/v1/auth/me": ok(testUser({ email_verified: false })),
      "POST /api/v1/auth/resend-verification": ok({ status: "accepted" }, 202),
    });
    renderWithProviders(<VerifyEmail />, { session: testUser({ email_verified: false }) });
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or has expired");
    click(screen.getByRole("button", { name: "Send a new verification link" }));
    expect(await screen.findByText(/sent a new verification link/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/api/v1/auth/resend-verification")).toBe(true);
  });

  it("asks signed-out visitors to sign in to get a new link", async () => {
    window.history.replaceState(null, "", "/verify-email#token=tok_abcdefghijklmnopqrst");
    mockApi({ "POST /api/v1/auth/verify-email": fail(400, "INVALID_TOKEN") });
    renderWithProviders(<VerifyEmail />, { session: null });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("handles a link without a token, without calling the API", async () => {
    const api = mockApi({});
    renderWithProviders(<VerifyEmail />, { session: null });
    expect(await screen.findByRole("alert")).toHaveTextContent("link is incomplete");
    expect(api.calls.some((c) => c.path === "/api/v1/auth/verify-email")).toBe(false);
  });
});
