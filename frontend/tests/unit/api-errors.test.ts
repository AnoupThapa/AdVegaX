import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  ApiError,
  KNOWN_ERROR_CODES,
  NETWORK_ERROR,
  UNEXPECTED_RESPONSE,
  apiErrorFrom,
  friendlyMessage,
  messageFor,
} from "@/lib/api/errors";

describe("apiErrorFrom", () => {
  it("reads the standard error envelope", () => {
    const error = apiErrorFrom(422, {
      error: {
        code: "VALIDATION_ERROR",
        message: "server text",
        details: [{ location: ["body", "email"], message: "Enter a valid email", type: "x" }],
      },
      meta: { request_id: "req-1" },
    });
    expect([error.status, error.code, error.requestId]).toEqual([422, "VALIDATION_ERROR", "req-1"]);
    expect(error.fieldErrors("email")).toEqual(["Enter a valid email"]);
    expect(error.fieldErrors("password")).toEqual([]);
  });

  it("falls back for missing or malformed bodies", () => {
    expect(apiErrorFrom(500, null).code).toBe("INTERNAL_ERROR");
    expect(apiErrorFrom(418, "teapot").code).toBe(UNEXPECTED_RESPONSE);
    expect(apiErrorFrom(400, { error: "nope" }).code).toBe(UNEXPECTED_RESPONSE);
    expect(apiErrorFrom(400, { error: { code: 5 } }).code).toBe(UNEXPECTED_RESPONSE);
    const headers = new Headers({ "x-request-id": "h-1" });
    expect(apiErrorFrom(404, { error: { code: "NOT_FOUND" } }, headers).requestId).toBe("h-1");
    expect(apiErrorFrom(404, { error: { code: "NOT_FOUND" } }).details).toEqual([]);
  });
});

describe("friendlyMessage", () => {
  it("never shows server text", () => {
    const error = new ApiError(400, "VALIDATION_ERROR");
    expect(friendlyMessage(error)).not.toContain("server text");
    expect(friendlyMessage("SOMETHING_NEW")).toBe("Something went wrong. Please try again.");
    expect(friendlyMessage(NETWORK_ERROR)).toMatch(/could not reach/);
  });

  it("messageFor covers anything thrown", () => {
    expect(messageFor(new ApiError(429, "RATE_LIMITED"))).toMatch(/Too many attempts/);
    expect(messageFor(new Error("boom"))).toBe("Something went wrong. Please try again.");
    expect(messageFor("text")).toBe("Something went wrong. Please try again.");
  });

  it("has a message for every error code the backend can return", () => {
    // Scan backend sources for `code = "..."` declarations so new codes cannot be missed.
    const backend = path.resolve(__dirname, "../../../backend/app");
    const codes = new Set<string>();
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith(".py")) {
          // Codes are declared three ways in the backend: `code = "X"` on error classes,
          // `error_body("X", ...)` and `("X", "message")` tuples in core/errors.py.
          const source = readFileSync(full, "utf8");
          for (const pattern of [
            /\bcode = "([A-Z][A-Z_]+)"/g,
            /\berror_body\(\s*"([A-Z][A-Z_]+)"/g,
            /\(\s*"([A-Z][A-Z_]+)",\s*"/g,
          ]) {
            for (const m of source.matchAll(pattern)) {
              codes.add(m[1] as string);
            }
          }
        }
      }
    };
    walk(backend);
    expect(codes.size).toBeGreaterThan(15);
    // The patterns that the first version of this scan missed.
    for (const code of ["HTTP_ERROR", "INTERNAL_ERROR", "METHOD_NOT_ALLOWED"]) {
      expect(codes).toContain(code);
    }
    const missing = [...codes].filter((c) => !KNOWN_ERROR_CODES.includes(c));
    expect(missing).toEqual([]);
  });
});
