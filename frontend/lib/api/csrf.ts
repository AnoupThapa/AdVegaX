/**
 * In-memory CSRF token (PHASE_01C_PLAN §4.2). Never written to browser storage or cookies.
 * The API binds the token to the session, so it is cleared whenever the session changes.
 */

let token: string | null = null;
let pending: Promise<string> | null = null;

export function getCsrfToken(): string | null {
  return token;
}

export function setCsrfToken(value: string | null): void {
  token = value;
}

export function clearCsrfToken(): void {
  token = null;
}

/** Returns the current token, fetching one from `GET /api/v1/auth/csrf` if needed. */
export async function ensureCsrfToken(fetchFn: typeof fetch, apiOrigin: string): Promise<string> {
  if (token) return token;
  pending ??= (async () => {
    try {
      const response = await fetchFn(`${apiOrigin}/api/v1/auth/csrf`, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const body: unknown = response.ok ? await response.json() : null;
      const value = (body as { data?: { csrf_token?: unknown } } | null)?.data?.csrf_token;
      if (typeof value !== "string" || !value) {
        throw new Error("csrf_unavailable");
      }
      token = value;
      return value;
    } finally {
      pending = null;
    }
  })();
  return pending;
}
