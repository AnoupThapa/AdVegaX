import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createApiClient, unwrap } from "@/lib/api/client";
import { clearCsrfToken, getCsrfToken, setCsrfToken } from "@/lib/api/csrf";
import { ApiError, NETWORK_ERROR } from "@/lib/api/errors";

const ORIGIN = "https://api.example.com";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

const csrfResponse = (token: string) => json(200, { data: { csrf_token: token }, meta: {} });
const me = { data: { id: "u1", email: "a@example.com" }, meta: { request_id: "r1" } };

type Call = { url: string; method: string; csrf: string | null; credentials: string; body: string };

function harness(responses: Array<Response | Error>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    calls.push({
      url: request.url,
      method: request.method,
      csrf: request.headers.get("X-CSRF-Token"),
      credentials: request.credentials,
      body: request.method === "GET" ? "" : await request.clone().text(),
    });
    const next = responses.shift();
    if (!next) throw new Error("unexpected request " + request.url);
    if (next instanceof Error) throw next;
    return next;
  });
  const onUnauthenticated = vi.fn();
  const client = createApiClient({
    apiOrigin: ORIGIN,
    fetch: fetchMock as unknown as typeof fetch,
    onUnauthenticated,
  });
  return { client, calls, fetchMock, onUnauthenticated };
}

beforeEach(() => clearCsrfToken());
afterEach(() => clearCsrfToken());

describe("API client", () => {
  it("sends reads with the session cookie and no CSRF token", async () => {
    const { client, calls } = harness([json(200, me)]);
    const data = await unwrap(client.GET("/api/v1/auth/me"));
    expect(data).toEqual(me.data);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      url: `${ORIGIN}/api/v1/auth/me`,
      method: "GET",
      csrf: null,
      credentials: "include",
    });
  });

  it("fetches a CSRF token once and sends it on unsafe requests", async () => {
    const { client, calls } = harness([
      csrfResponse("tok-1"),
      json(202, { data: { status: "accepted" }, meta: {} }),
      json(202, { data: { status: "accepted" }, meta: {} }),
    ]);
    const body = { email: "a@example.com" };
    await unwrap(client.POST("/api/v1/auth/forgot-password", { body }));
    await unwrap(client.POST("/api/v1/auth/forgot-password", { body }));
    expect(calls.map((c) => [c.method, new URL(c.url).pathname, c.csrf])).toEqual([
      ["GET", "/api/v1/auth/csrf", null],
      ["POST", "/api/v1/auth/forgot-password", "tok-1"],
      ["POST", "/api/v1/auth/forgot-password", "tok-1"],
    ]);
    expect(calls[0]?.credentials).toBe("include");
    expect(JSON.parse(calls[1]?.body ?? "")).toEqual(body);
  });

  it("stores the fresh token returned when the session rotates", async () => {
    setCsrfToken("anon");
    const { client, calls } = harness([
      json(200, { data: { user: { id: "u1" }, csrf_token: "session-tok" }, meta: {} }),
      json(200, { data: { status: "signed_out", csrf_token: "anon-2" }, meta: {} }),
    ]);
    await unwrap(
      client.POST("/api/v1/auth/login", { body: { email: "a@example.com", password: "x" } }),
    );
    expect(getCsrfToken()).toBe("session-tok");
    await unwrap(client.POST("/api/v1/auth/logout"));
    expect(calls[1]?.csrf).toBe("session-tok");
    expect(getCsrfToken()).toBe("anon-2");
  });

  it("refreshes the token and retries exactly once after CSRF_FAILED, resending the body", async () => {
    setCsrfToken("stale");
    const csrfFailed = () => json(403, { error: { code: "CSRF_FAILED" }, meta: {} });
    const { client, calls } = harness([
      csrfFailed(),
      csrfResponse("fresh"),
      json(202, { data: { status: "accepted" }, meta: {} }),
    ]);
    const body = { email: "retry@example.com" };
    await unwrap(client.POST("/api/v1/auth/forgot-password", { body }));
    expect(calls.map((c) => c.csrf)).toEqual(["stale", null, "fresh"]);
    expect(JSON.parse(calls[2]?.body ?? "")).toEqual(body);

    // A second failure is returned, never retried in a loop.
    const again = harness([csrfFailed(), csrfResponse("fresh-2"), csrfFailed()]);
    setCsrfToken("stale");
    const error = await unwrap(again.client.POST("/api/v1/auth/forgot-password", { body })).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("CSRF_FAILED");
    expect(again.calls).toHaveLength(3);
  });

  it("does not retry other 403 answers", async () => {
    setCsrfToken("t");
    const { client, calls } = harness([json(403, { error: { code: "FORBIDDEN" }, meta: {} })]);
    const error = await unwrap(
      client.POST("/api/v1/organizations/{organization_id}/connections/{provider}/start", {
        params: {
          path: { organization_id: "00000000-0000-0000-0000-000000000000", provider: "x" },
        },
      }),
    ).catch((e: unknown) => e);
    expect((error as ApiError).code).toBe("FORBIDDEN");
    expect(calls).toHaveLength(1);
  });

  it("on 401 clears the CSRF token and notifies the app", async () => {
    setCsrfToken("t");
    const { client, onUnauthenticated } = harness([
      json(401, { error: { code: "UNAUTHENTICATED" }, meta: { request_id: "req-9" } }),
    ]);
    const error = (await unwrap(client.GET("/api/v1/auth/me")).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.status).toBe(401);
    expect(error.code).toBe("UNAUTHENTICATED");
    expect(error.requestId).toBe("req-9");
    expect(getCsrfToken()).toBeNull();
    expect(onUnauthenticated).toHaveBeenCalledOnce();
  });

  it("a wrong password (401 INVALID_CREDENTIALS) does not end the session", async () => {
    setCsrfToken("session-token");
    const { client, onUnauthenticated } = harness([
      json(401, { error: { code: "INVALID_CREDENTIALS" }, meta: {} }),
    ]);
    const error = (await unwrap(
      client.POST("/api/v1/auth/change-password", {
        body: { current_password: "wrong", new_password: "correct horse battery staple" },
      }),
    ).catch((e: unknown) => e)) as ApiError;
    expect([error.status, error.code]).toEqual([401, "INVALID_CREDENTIALS"]);
    expect(onUnauthenticated).not.toHaveBeenCalled();
    expect(getCsrfToken()).toBe("session-token");
  });

  it("a 401 without a readable body still ends the session", async () => {
    setCsrfToken("t");
    const { client, onUnauthenticated } = harness([new Response("", { status: 401 })]);
    await unwrap(client.GET("/api/v1/auth/me")).catch(() => null);
    expect(onUnauthenticated).toHaveBeenCalledOnce();
    expect(getCsrfToken()).toBeNull();
  });

  it("maps network failures to NETWORK_ERROR", async () => {
    const offline = harness([new TypeError("Failed to fetch")]);
    const error = (await unwrap(offline.client.GET("/api/v1/auth/me")).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect([error.status, error.code]).toEqual([0, NETWORK_ERROR]);

    const noCsrf = harness([new TypeError("Failed to fetch")]);
    const unsafe = (await unwrap(
      noCsrf.client.POST("/api/v1/auth/forgot-password", { body: { email: "a@example.com" } }),
    ).catch((e: unknown) => e)) as ApiError;
    expect(unsafe.code).toBe(NETWORK_ERROR);
  });

  it("treats an unusable CSRF answer as a network failure", async () => {
    const { client } = harness([json(503, { error: { code: "SERVICE_UNAVAILABLE" } })]);
    const error = (await unwrap(
      client.POST("/api/v1/auth/forgot-password", { body: { email: "a@example.com" } }),
    ).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe(NETWORK_ERROR);
  });

  it("maps non-JSON server errors without exposing the body", async () => {
    const { client } = harness([
      new Response("<html>stack trace</html>", {
        status: 502,
        headers: { "content-type": "text/html", "x-request-id": "edge-1" },
      }),
    ]);
    const error = (await unwrap(client.GET("/api/v1/auth/me")).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect([error.status, error.code, error.requestId]).toEqual([502, "INTERNAL_ERROR", "edge-1"]);
    expect(error.message).not.toContain("stack");
  });

  it("shares one CSRF request between concurrent unsafe calls", async () => {
    const { client, calls } = harness([
      csrfResponse("shared"),
      json(202, { data: { status: "accepted" }, meta: {} }),
      json(202, { data: { status: "accepted" }, meta: {} }),
    ]);
    const body = { email: "a@example.com" };
    await Promise.all([
      unwrap(client.POST("/api/v1/auth/forgot-password", { body })),
      unwrap(client.POST("/api/v1/auth/forgot-password", { body })),
    ]);
    expect(calls.filter((c) => c.url.endsWith("/auth/csrf"))).toHaveLength(1);
    expect(calls.filter((c) => c.csrf === "shared")).toHaveLength(2);
  });

  it("ignores an unreadable JSON body instead of failing", async () => {
    const { client } = harness([
      new Response("{not json", { status: 500, headers: { "content-type": "application/json" } }),
    ]);
    const error = (await unwrap(client.GET("/api/v1/auth/me")).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect([error.status, error.code]).toEqual([500, "INTERNAL_ERROR"]);
  });
});
