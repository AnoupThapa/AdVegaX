/**
 * Content-Security-Policy with a per-request nonce (PHASE_01C_PLAN §7).
 * Scripts run only with the nonce ('strict-dynamic' lets Next.js load its own chunks).
 */

export type CspOptions = {
  readonly nonce: string;
  /** Origin the browser may call (the AdVegaX API). */
  readonly apiOrigin: string;
  /** Development tooling needs 'unsafe-eval' for React debugging and inline styles for its overlay. */
  readonly isDev: boolean;
};

const NONCE_BYTES = 16;

export function generateNonce(): string {
  const bytes = new Uint8Array(NONCE_BYTES);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function buildContentSecurityPolicy({ nonce, apiOrigin, isDev }: CspOptions): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      ...(isDev ? ["'unsafe-eval'"] : []),
    ],
    "style-src": ["'self'", isDev ? "'unsafe-inline'" : `'nonce-${nonce}'`],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'", apiOrigin],
    "object-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
    "frame-src": ["'none'"],
    "worker-src": ["'self'", "blob:"],
    "manifest-src": ["'self'"],
  };
  const policy = Object.entries(directives).map(([name, values]) => `${name} ${values.join(" ")}`);
  // Only when the deployment is on https; a local production build talks to http://localhost.
  if (!isDev && apiOrigin.startsWith("https://")) {
    policy.push("upgrade-insecure-requests");
  }
  return policy.join("; ");
}
