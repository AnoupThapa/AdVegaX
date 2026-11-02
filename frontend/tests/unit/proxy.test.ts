import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { config, proxy } from "@/proxy";

function cspOf(value: string | null): Map<string, string> {
  return new Map(
    (value ?? "").split("; ").map((part) => {
      const index = part.indexOf(" ");
      return index === -1 ? [part, ""] : [part.slice(0, index), part.slice(index + 1)];
    }),
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("proxy", () => {
  it("sets a fresh nonce CSP on the response and forwards it to Next.js", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000");
    const first = proxy(new NextRequest("http://localhost:3000/"));
    const second = proxy(new NextRequest("http://localhost:3000/"));

    const csp = first.headers.get("Content-Security-Policy");
    expect(csp).toBeTruthy();
    expect(cspOf(csp).get("connect-src")).toBe("'self' http://localhost:8000");
    expect(csp).not.toBe(second.headers.get("Content-Security-Policy"));

    const nonce = /'nonce-([^']+)'/.exec(csp ?? "")?.[1];
    expect(nonce).toBeTruthy();
    // Request-header overrides are how Next.js receives the nonce for its own scripts.
    expect(first.headers.get("x-middleware-request-x-nonce")).toBe(nonce);
    expect(first.headers.get("x-middleware-request-content-security-policy")).toBe(csp);
    expect(first.headers.get("Strict-Transport-Security")).toBeNull();
  });

  it("adds HSTS when the API is served over https", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.example.com");
    const response = proxy(new NextRequest("https://app.example.com/"));
    expect(response.headers.get("Strict-Transport-Security")).toBe(
      "max-age=63072000; includeSubDomains",
    );
  });

  it("uses the development policy only in development", () => {
    vi.stubEnv("NODE_ENV", "development");
    const dev = proxy(new NextRequest("http://localhost:3000/"));
    expect(dev.headers.get("Content-Security-Policy")).toContain("'unsafe-eval'");
    vi.stubEnv("NODE_ENV", "production");
    const prod = proxy(new NextRequest("http://localhost:3000/"));
    expect(prod.headers.get("Content-Security-Policy")).not.toContain("'unsafe-eval'");
  });

  it("covers pages but skips static assets and prefetches", () => {
    const [matcher] = config.matcher;
    expect(matcher?.source).toBe("/((?!_next/static|_next/image|favicon.ico).*)");
    expect(matcher?.missing.map((m) => m.key)).toEqual(["next-router-prefetch", "purpose"]);
  });
});
