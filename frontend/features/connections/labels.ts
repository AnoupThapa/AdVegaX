/** Plain-language wording for connection states, platform callback results and errors. */

export const CONNECTION_STATUS: Readonly<
  Record<string, { label: string; tone: "ok" | "warn" | "off" }>
> = {
  active: { label: "Connected", tone: "ok" },
  expired: { label: "Needs reconnecting", tone: "warn" },
  error: { label: "Problem", tone: "warn" },
  revoked: { label: "Disconnected", tone: "off" },
};

export function connectionStatus(status: string) {
  return CONNECTION_STATUS[status] ?? { label: status, tone: "warn" as const };
}

export const RESOURCE_KIND: Readonly<Record<string, string>> = {
  store: "Store",
  ad_account: "Ad account",
  analytics_property: "Analytics property",
  business_asset: "Business asset",
};

export const UNLINK_REASON: Readonly<Record<string, string>> = {
  user: "Unlinked by a member",
  connection_revoked: "Connection disconnected",
  resource_inaccessible: "No longer accessible through the connection",
};

/** Error codes from the platform (via the API) and from the connect flow. */
const CONNECT_ERRORS: Readonly<Record<string, string>> = {
  invalid_state:
    "This connection attempt expired or was already used. Please start connecting again.",
  session_mismatch:
    "This connection was started by a different account, or you were signed out. Sign in and start again.",
  not_permitted: "You no longer have permission to manage connections in that organization.",
  invalid_request: "The platform did not accept the connection. Please try again.",
  auth_expired: "The platform's permission has expired. Please reconnect.",
  permission_denied:
    "The platform account does not allow this access. Check its permissions, then reconnect.",
  rate_limited: "The platform is busy right now. Please try again in a few minutes.",
  credentials_missing: "This connection's sign-in details are missing. Please reconnect.",
  credentials_unreadable: "This connection's sign-in details could not be read. Please reconnect.",
};

export function connectError(code: string | null | undefined): string {
  return (
    (code && CONNECT_ERRORS[code]) || "Something went wrong with the platform. Please try again."
  );
}

export const JOB_STATUS: Readonly<Record<string, string>> = {
  queued: "Waiting to start",
  running: "In progress",
  succeeded: "Finished",
  failed: "Failed",
  dead: "Failed after several tries",
};
