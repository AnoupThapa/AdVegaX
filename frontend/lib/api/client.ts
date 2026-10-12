/**
 * Typed API client (PHASE_01C_PLAN §4.1–4.2).
 *
 * - Types come from the generated OpenAPI schema (`schema.d.ts`), so calls are checked at build time.
 * - Every request is sent from the browser straight to the API with the session cookie
 *   (`credentials: "include"`). The Next.js server is never involved.
 * - Unsafe requests carry the in-memory CSRF token; a `CSRF_FAILED` answer refreshes the token
 *   and retries exactly once.
 * - A 401 clears the CSRF token and calls `onUnauthenticated` (the app sends the person to sign in),
 *   except `INVALID_CREDENTIALS` (a wrong password), which leaves the session alone.
 */

import createClient, { type Client } from "openapi-fetch";

import { clearCsrfToken, ensureCsrfToken, setCsrfToken } from "./csrf";
import { ApiError, NETWORK_ERROR, apiErrorFrom } from "./errors";
import type { paths } from "./schema";

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CSRF_HEADER = "X-CSRF-Token";

export type ApiClientOptions = {
  readonly apiOrigin: string;
  readonly fetch?: typeof fetch;
  readonly onUnauthenticated?: () => void;
};

export type ApiClient = Client<paths>;

async function readJson(response: Response): Promise<unknown> {
  if (!response.headers.get("content-type")?.includes("application/json")) return null;
  try {
    return await response.clone().json();
  } catch {
    return null;
  }
}

/** The fetch function used by the client: CSRF, retry and session handling live here. */
export function createApiFetch(options: ApiClientOptions): (input: Request) => Promise<Response> {
  // Resolved per call so the page's current fetch is used (and tests can replace it).
  const baseFetch: typeof fetch = options.fetch ?? ((input, init) => globalThis.fetch(input, init));

  async function send(request: Request, retried: boolean): Promise<Response> {
    const unsafe = UNSAFE.has(request.method);
    const spare = unsafe && !retried ? request.clone() : null;
    if (unsafe) {
      let csrf: string;
      try {
        csrf = await ensureCsrfToken(baseFetch, options.apiOrigin);
      } catch {
        throw new ApiError(0, NETWORK_ERROR);
      }
      request.headers.set(CSRF_HEADER, csrf);
    }

    let response: Response;
    try {
      response = await baseFetch(request);
    } catch {
      throw new ApiError(0, NETWORK_ERROR);
    }

    const body = await readJson(response);

    // A 401 means the session is gone — except INVALID_CREDENTIALS, which only says a password
    // was wrong (sign-in, or the current password when changing it) and leaves the session intact.
    if (response.status === 401) {
      const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
      if (code !== "INVALID_CREDENTIALS") {
        clearCsrfToken();
        options.onUnauthenticated?.();
      }
      return response;
    }

    if (unsafe && response.status === 403 && spare) {
      const code = (body as { error?: { code?: unknown } } | null)?.error?.code;
      if (code === "CSRF_FAILED") {
        clearCsrfToken();
        return send(spare, true);
      }
    }

    // Login, logout and password changes rotate the session and return a fresh token.
    const fresh = (body as { data?: { csrf_token?: unknown } } | null)?.data?.csrf_token;
    if (response.ok && typeof fresh === "string" && fresh) {
      setCsrfToken(fresh);
    }
    return response;
  }

  return (input: Request) => send(input, false);
}

export function createApiClient(options: ApiClientOptions): ApiClient {
  return createClient<paths>({
    baseUrl: options.apiOrigin,
    credentials: "include",
    headers: { Accept: "application/json" },
    fetch: createApiFetch(options),
  });
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/**
 * Unwraps an openapi-fetch result: returns the envelope's `data` or throws an `ApiError`.
 *
 *   const me = await unwrap(api.GET("/api/v1/auth/me"));
 */
export async function unwrap<T extends { data: unknown }>(
  call: Promise<Result<T>>,
): Promise<T["data"]> {
  const result = await call;
  if (result.response.ok && result.data !== undefined) {
    return result.data.data;
  }
  throw apiErrorFrom(result.response.status, result.error, result.response.headers);
}
