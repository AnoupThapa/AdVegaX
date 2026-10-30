/**
 * A fake AdVegaX API for component tests: replaces global fetch, routes by "METHOD /path",
 * records every call. Requests still go through the real API client (CSRF, errors, retries).
 */
import { vi } from "vitest";

export type MockCall = {
  method: string;
  path: string;
  body: unknown;
  csrf: string | null;
  /** The query string's values (e.g. `breakdown`), for routes answered by one handler. */
  query: URLSearchParams;
};
type Handler = (call: MockCall) => Response | Promise<Response>;

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export const ok = (data: unknown, status = 200) =>
  json(status, { data, meta: { request_id: "req-test" } });

export const fail = (status: number, code: string, details: unknown[] = []) =>
  json(status, {
    error: { code, message: "server text", details },
    meta: { request_id: "req-err" },
  });

/** JSON bodies are parsed; anything else (a multipart upload) is kept as text. */
function parseBody(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export function mockApi(routes: Record<string, Handler | Response>) {
  const calls: MockCall[] = [];
  const handlers = new Map<string, Handler>(
    Object.entries(routes).map(([k, v]) => [k, typeof v === "function" ? v : () => v.clone()]),
  );
  // Every unsafe request needs a CSRF token first.
  if (!handlers.has("GET /api/v1/auth/csrf")) {
    handlers.set("GET /api/v1/auth/csrf", () => ok({ csrf_token: "csrf-test" }));
  }
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    const url = new URL(request.url);
    const text = request.method === "GET" ? "" : await request.clone().text();
    const call: MockCall = {
      method: request.method,
      path: url.pathname,
      body: text ? parseBody(text) : null,
      csrf: request.headers.get("X-CSRF-Token"),
      query: url.searchParams,
    };
    calls.push(call);
    const handler = handlers.get(`${call.method} ${call.path}`);
    if (!handler) return fail(404, "NOT_FOUND");
    return handler(call);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    /** Calls other than the CSRF bootstrap. */
    apiCalls: () => calls.filter((c) => c.path !== "/api/v1/auth/csrf"),
    set(route: string, handler: Handler | Response) {
      handlers.set(route, typeof handler === "function" ? handler : () => handler.clone());
    },
  };
}
