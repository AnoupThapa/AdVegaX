import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm } from "@/features/auth/ForgotPasswordForm";
import { ResetPasswordForm } from "@/features/auth/ResetPasswordForm";
import { SESSION_KEY } from "@/features/auth/session";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { resetNavigation } from "../support/navigation";
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

const TOKEN = "reset_abcdefghijklmnopqrstu";

describe("Forgot password", () => {
  it("validates the email, then shows the same confirmation for any address", async () => {
    const api = mockApi({ "POST /api/v1/auth/forgot-password": ok({ status: "accepted" }, 202) });
    renderWithProviders(<ForgotPasswordForm />, { session: null });
    click(screen.getByRole("button", { name: "Send reset link" }));
    expect(screen.getByLabelText("Email")).toHaveFocus();
    fill(screen.getByLabelText("Email"), "someone@example.com");
    click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If an account exists");
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
      email: "someone@example.com",
    });
  });

  it("explains network failures", async () => {
    mockApi({
      "POST /api/v1/auth/forgot-password": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderWithProviders(<ForgotPasswordForm />, { session: null });
    fill(screen.getByLabelText("Email"), "someone@example.com");
    click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not reach AdVegaX");
  });
});

describe("Reset password", () => {
  it("hides the token, checks both fields and signs this browser out on success", async () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    const api = mockApi({
      "POST /api/v1/auth/reset-password": ok({ status: "reset", csrf_token: "anon" }),
      "GET /api/v1/auth/me": fail(401, "UNAUTHENTICATED"),
    });
    const { queryClient } = renderWithProviders(<ResetPasswordForm />, { session: testUser() });
    const password = await screen.findByLabelText("New password");
    expect(window.location.href).not.toContain(TOKEN);

    fill(password, "correct horse battery staple");
    fill(screen.getByLabelText("Confirm new password"), "different horse battery");
    click(screen.getByRole("button", { name: "Save new password" }));
    expect(screen.getByLabelText("Confirm new password")).toHaveAccessibleDescription(
      "The passwords do not match.",
    );

    fill(screen.getByLabelText("Confirm new password"), "correct horse battery staple");
    click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByRole("status")).toHaveTextContent("signed out on every device");
    expect(api.calls.find((c) => c.path === "/api/v1/auth/reset-password")?.body).toEqual({
      token: TOKEN,
      new_password: "correct horse battery staple",
    });
    await waitFor(() => expect(queryClient.getQueryData(SESSION_KEY)).toBeNull());
  });

  it("maps the API's password field onto the new-password input", async () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    mockApi({
      "POST /api/v1/auth/reset-password": fail(422, "VALIDATION_ERROR", [
        {
          location: ["body", "password"],
          message: "Password must not be your email address.",
          type: "password_policy",
        },
      ]),
    });
    renderWithProviders(<ResetPasswordForm />, { session: null });
    fill(await screen.findByLabelText("New password"), "ada@example.com12");
    fill(screen.getByLabelText("Confirm new password"), "ada@example.com12");
    click(screen.getByRole("button", { name: "Save new password" }));
    await screen.findByRole("alert");
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      expect.stringContaining("Password must not be your email address."),
    );
  });

  it("offers a new link when the token is used or expired", async () => {
    window.history.replaceState(null, "", `/reset-password#token=${TOKEN}`);
    mockApi({ "POST /api/v1/auth/reset-password": fail(400, "INVALID_TOKEN") });
    renderWithProviders(<ResetPasswordForm />, { session: null });
    fill(await screen.findByLabelText("New password"), "correct horse battery staple");
    fill(screen.getByLabelText("Confirm new password"), "correct horse battery staple");
    click(screen.getByRole("button", { name: "Save new password" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("invalid or has expired");
    expect(screen.getByRole("link", { name: "Request a new reset link" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("handles a link without a token", async () => {
    mockApi({});
    renderWithProviders(<ResetPasswordForm />, { session: null });
    expect(await screen.findByRole("alert")).toHaveTextContent("reset link is incomplete");
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });
});
