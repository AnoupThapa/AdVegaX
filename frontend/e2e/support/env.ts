/** Addresses of the stack under test. Defaults match the local development setup. */
export const WEB = process.env.E2E_WEB_URL ?? "http://localhost:3000";
export const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

/** Test-only password used for every account the suite creates. */
export const PASSWORD = "correct horse battery staple";

export function uniqueEmail(tag: string): string {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return `e2e-${tag}-${suffix}@example.com`;
}
