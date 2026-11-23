/**
 * Leaves the app for a platform's sign-in page. Only https addresses are allowed, so a
 * tampered or misconfigured URL can never run script or downgrade to plain http.
 */
export function goToExternal(
  url: string,
  navigate: (href: string) => void = (href) => window.location.assign(href),
): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) return false;
  navigate(parsed.toString());
  return true;
}
