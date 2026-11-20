import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";

import { readAndClearFragmentToken } from "@/features/auth/fragment-token";
import { formFeedback } from "@/features/auth/form-errors";
import { SESSION_KEY, handleSessionEnded } from "@/features/auth/session";
import { emailErrors, hasErrors, newPasswordErrors } from "@/features/auth/validation";
import { ApiError } from "@/lib/api/errors";

describe("client-side checks", () => {
  it("email", () => {
    expect(emailErrors("")).toEqual(["Enter your email address."]);
    expect(emailErrors("not-an-email")).toEqual(["Enter a valid email address."]);
    expect(emailErrors(`${"a".repeat(250)}@x.com`)).toEqual(["Enter a valid email address."]);
    expect(emailErrors("  ada@example.com ")).toEqual([]);
  });

  it("new password mirrors the API policy", () => {
    expect(newPasswordErrors("")).toEqual(["Enter a password."]);
    expect(newPasswordErrors("short")).toEqual(["Use at least 12 characters."]);
    expect(newPasswordErrors("x".repeat(129))).toEqual(["Use at most 128 characters."]);
    expect(newPasswordErrors("Ada@Example.com1", "ada@example.com1")).toEqual([
      "Your password must not be your email address.",
    ]);
    expect(newPasswordErrors("correct horse battery staple", "ada@example.com")).toEqual([]);
    expect(hasErrors({ a: [], b: undefined })).toBe(false);
    expect(hasErrors({ a: ["x"] })).toBe(true);
  });
});

describe("formFeedback", () => {
  it("shows password-policy messages but hides other server wording", () => {
    const error = new ApiError(
      422,
      "VALIDATION_ERROR",
      [
        {
          location: ["body", "password"],
          message: "Password must be at least 12 characters.",
          type: "password_policy",
        },
        {
          location: ["body", "email"],
          message: "String should have at least 3 characters",
          type: "string_too_short",
        },
        { location: ["body", "email"], message: "dup", type: "other" },
        { message: "no location" },
      ],
      "req-1",
    );
    const feedback = formFeedback(error, { password: "new_password" });
    expect(feedback.fields).toEqual({
      new_password: ["Password must be at least 12 characters."],
      email: ["Check this field and try again."],
    });
    expect(feedback.message).toBe("Some details are missing or invalid. Please check the form.");
    expect(feedback.requestId).toBe("req-1");
  });

  it("handles non-validation and non-API errors", () => {
    expect(formFeedback(new ApiError(429, "RATE_LIMITED")).fields).toEqual({});
    expect(formFeedback(new Error("boom")).message).toBe("Something went wrong. Please try again.");
  });
});

describe("fragment token", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("reads a valid token and removes it from the address bar", () => {
    window.history.replaceState(null, "", "/verify-email?x=1#token=abcdefghijklmnop_-123");
    expect(readAndClearFragmentToken()).toBe("abcdefghijklmnop_-123");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/verify-email?x=1");
  });

  it.each(["", "#token=short", "#token=has spaces in it ok", "#other=abcdefghijklmnopqrst"])(
    "rejects %j and still clears the fragment",
    (hash) => {
      window.history.replaceState(null, "", `/reset-password${hash}`);
      expect(readAndClearFragmentToken()).toBeNull();
      expect(window.location.hash).toBe("");
    },
  );
});

describe("handleSessionEnded", () => {
  it("is a no-op when already signed out (no refetch loop)", () => {
    const client = new QueryClient();
    client.setQueryData(SESSION_KEY, null);
    client.setQueryData(["public"], 1);
    handleSessionEnded(client);
    expect(client.getQueryData(["public"])).toBe(1);
  });

  it("drops signed-in data and marks the session signed out", () => {
    const client = new QueryClient();
    client.setQueryData(SESSION_KEY, { id: "u" });
    client.setQueryData(["orgs"], [1]);
    handleSessionEnded(client);
    expect(client.getQueryData(SESSION_KEY)).toBeNull();
    expect(client.getQueryData(["orgs"])).toBeUndefined();
  });
});
