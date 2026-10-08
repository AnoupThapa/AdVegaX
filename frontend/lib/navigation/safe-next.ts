/**
 * Validates a post-sign-in `next` destination (PHASE_01C_PLAN §4.2, §7).
 * Only same-origin relative paths are allowed; anything else falls back. Prevents open redirects.
 */

const PLACEHOLDER_ORIGIN = "https://advegax.invalid";
const MAX_LENGTH = 512;

export function safeNextPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw || raw.length > MAX_LENGTH) return fallback;
  // Must be a single leading slash: rejects "//host", "/\host", "https:", "javascript:" etc.
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  // Control characters, whitespace and backslashes are never part of our routes.
  if (/[\u0000-\u001f\u007f\s\\]/.test(raw)) return fallback;

  let url: URL;
  try {
    url = new URL(raw, PLACEHOLDER_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== PLACEHOLDER_ORIGIN) return fallback;
  return `${url.pathname}${url.search}${url.hash}`;
}
