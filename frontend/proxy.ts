import { NextResponse, type NextRequest } from "next/server";

import { publicConfig } from "@/lib/config/public-config";
import { buildContentSecurityPolicy, generateNonce } from "@/lib/security/csp";

const HSTS = "max-age=63072000; includeSubDomains";

/**
 * Runs before every page request (Next.js 16 "proxy", formerly middleware).
 * Sets a nonce-based Content-Security-Policy on both the request (so Next.js applies the
 * nonce to its own scripts) and the response. Holds no session and calls no API.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = generateNonce();
  const { apiOrigin } = publicConfig();
  const csp = buildContentSecurityPolicy({
    nonce,
    apiOrigin,
    isDev: process.env.NODE_ENV === "development",
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  if (apiOrigin.startsWith("https://")) {
    response.headers.set("Strict-Transport-Security", HSTS);
  }
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
