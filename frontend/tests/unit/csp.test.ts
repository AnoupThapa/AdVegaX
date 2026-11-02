import { describe, expect, it } from "vitest";

import { buildContentSecurityPolicy, generateNonce } from "@/lib/security/csp";

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split("; ").map((part) => {
      const [name = "", ...values] = part.split(" ");
      return [name, values];
    }),
  );
}

describe("generateNonce", () => {
  it("returns unpredictable 128-bit base64 values", () => {
    const values = new Set(Array.from({ length: 50 }, generateNonce));
    expect(values.size).toBe(50);
    for (const value of values) {
      expect(value).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    }
  });
});

describe("buildContentSecurityPolicy", () => {
  const base = { nonce: "abc123", apiOrigin: "https://api.example.com" };

  it("production policy allows scripts only with the nonce", () => {
    const policy = directives(buildContentSecurityPolicy({ ...base, isDev: false }));
    expect(policy.get("script-src")).toEqual(["'self'", "'nonce-abc123'", "'strict-dynamic'"]);
    expect(policy.get("style-src")).toEqual(["'self'", "'nonce-abc123'"]);
    expect(policy.get("connect-src")).toEqual(["'self'", "https://api.example.com"]);
    expect(policy.get("frame-ancestors")).toEqual(["'none'"]);
    expect(policy.get("object-src")).toEqual(["'none'"]);
    expect(policy.get("base-uri")).toEqual(["'none'"]);
    expect(policy.get("form-action")).toEqual(["'self'"]);
    expect(policy.has("upgrade-insecure-requests")).toBe(true);
    const text = buildContentSecurityPolicy({ ...base, isDev: false });
    expect(text).not.toContain("unsafe-inline");
    expect(text).not.toContain("unsafe-eval");
    expect(text).not.toContain("*");
  });

  it("development relaxes only what the dev tooling needs", () => {
    const policy = directives(buildContentSecurityPolicy({ ...base, isDev: true }));
    expect(policy.get("script-src")).toContain("'unsafe-eval'");
    expect(policy.get("script-src")).not.toContain("'unsafe-inline'");
    expect(policy.get("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
    expect(policy.has("upgrade-insecure-requests")).toBe(false);
  });

  it("does not upgrade requests for a local production build", () => {
    const policy = directives(
      buildContentSecurityPolicy({ ...base, apiOrigin: "http://localhost:8000", isDev: false }),
    );
    expect(policy.has("upgrade-insecure-requests")).toBe(false);
    expect(policy.get("connect-src")).toEqual(["'self'", "http://localhost:8000"]);
  });
});
