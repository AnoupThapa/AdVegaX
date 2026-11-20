/**
 * Public (browser-visible) configuration. Only NEXT_PUBLIC_* values belong here — never secrets (D15).
 */

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const DEFAULT_API_BASE_URL = "http://localhost:8000";

export type PublicConfig = {
  /** Origin of the AdVegaX API, e.g. "https://api.example.com" (no trailing slash, no path). */
  readonly apiOrigin: string;
};

export class PublicConfigError extends Error {
  override readonly name = "PublicConfigError";
}

type Env = Readonly<Record<string, string | undefined>>;

export function parsePublicConfig(env: Env): PublicConfig {
  const raw = env.NEXT_PUBLIC_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new PublicConfigError("NEXT_PUBLIC_API_BASE_URL must be an absolute URL");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new PublicConfigError("NEXT_PUBLIC_API_BASE_URL must use https");
  }
  if (url.username || url.password) {
    throw new PublicConfigError("NEXT_PUBLIC_API_BASE_URL must not contain credentials");
  }
  if ((url.pathname !== "/" && url.pathname !== "") || url.search || url.hash) {
    throw new PublicConfigError(
      "NEXT_PUBLIC_API_BASE_URL must be an origin only (no path, query or fragment)",
    );
  }
  if (url.protocol === "http:" && !LOCAL_HOSTS.has(url.hostname)) {
    throw new PublicConfigError(
      "NEXT_PUBLIC_API_BASE_URL must use https outside local development",
    );
  }
  return { apiOrigin: url.origin };
}

/** Throws at build/start time when the configuration is unsafe. */
export function assertPublicConfig(env: Env): void {
  parsePublicConfig(env);
}

export function publicConfig(): PublicConfig {
  // Next.js inlines NEXT_PUBLIC_* at build time only for direct property access.
  return parsePublicConfig({ NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL });
}
