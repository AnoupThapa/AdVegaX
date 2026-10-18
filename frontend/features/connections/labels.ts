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
  account_in_use:
    "This account is already connected to another AdVegaX organization. Ask its owner to disconnect it first.",
  invalid_connect_params: "Check the details you entered, for example the store address.",
  invalid_signature:
    "The platform's reply could not be verified, so nothing was connected. Please start again.",
  account_mismatch:
    "The platform answered for a different store or account than the one you chose. Please start again.",
  missing_scopes:
    "Some permissions AdVegaX needs were not approved. Please connect again and approve all of them.",
  unsupported: "This platform does not support that way of connecting.",
  account_busy:
    "AdVegaX was updating this connection at the same moment. Please wait a few seconds and try again.",
  app_uninstalled: "The AdVegaX app was uninstalled from this store. Reconnect to continue.",
  unknown_provider: "This platform is not available.",
  // WooCommerce (2B): the store's answer while connecting.
  key_not_delivered:
    "The store did not send AdVegaX its access key. If you approved access, check that the store can reach the internet, then connect again.",
  connect_failed: "The store's access could not be set up. Please connect again.",
  not_read_only:
    "The store offered more than read-only access, so nothing was saved. Please connect again and approve read access only.",
  woocommerce_too_old: "Please update WooCommerce to version 9.0 or newer, then connect again.",
  key_rejected:
    "The store did not accept its new access key. Check that the WordPress user who approved it is an administrator, then connect again.",
  auth_header_stripped:
    "Your web host removes the login details AdVegaX sends with each request. Ask your host to pass the Authorization header through to WordPress, then connect again.",
  woocommerce_api_not_found:
    "WooCommerce's API was not found at this address. Check that WooCommerce is installed and active and that the address is your WordPress site's.",
  store_redirected:
    "The store sent AdVegaX to a different address. Enter the address the store finally opens at (with https://), then connect again.",
  unexpected_response:
    "The platform gave an answer AdVegaX could not understand. Please try again.",
  // Google Ads (3-09).
  google_sign_in_rejected:
    "Google no longer accepts AdVegaX's permission (it was removed or expired). Please reconnect Google Ads.",
  not_ads_user:
    "This Google account has no Google Ads account. Sign in with the Google account you use for Google Ads.",
  developer_token_invalid:
    "AdVegaX's access to Google Ads is not set up correctly. Please contact AdVegaX support.",
  developer_token_not_approved:
    "Google has not yet approved AdVegaX for real ad accounts. Only test accounts can be read for now.",
  no_account_access:
    "This Google account no longer has access to that ad account. Ask its administrator for access, then check again.",
  account_not_enabled:
    "The ad account is cancelled, suspended or closed in Google Ads, so it cannot be read.",
  quota_exhausted:
    "Google Ads is limiting how much AdVegaX can read right now. It continues by itself later.",
  bad_query: "Google Ads did not accept AdVegaX's request. Please contact AdVegaX support.",
  server_error: "The store had a temporary problem. Please try again in a few minutes.",
  timeout: "The store took too long to answer. Please try again in a few minutes.",
};

const STORE_UNREACHABLE: Readonly<Record<string, string>> = {
  woocommerce_api_not_found: CONNECT_ERRORS.woocommerce_api_not_found as string,
  store_redirected: CONNECT_ERRORS.store_redirected as string,
  auth_header_stripped: CONNECT_ERRORS.auth_header_stripped as string,
  retryable: "The store did not answer. Check that it is online, then try again.",
};

/** Why AdVegaX could not use a store's address when starting to connect (STORE_NOT_REACHABLE). */
export function storeUnreachable(reason: string | null | undefined): string {
  return (
    (reason && STORE_UNREACHABLE[reason]) ||
    "AdVegaX could not reach the store's WooCommerce API at this address. Check the address and that the store is online."
  );
}

export function connectError(code: string | null | undefined): string {
  return (
    (code && CONNECT_ERRORS[code]) || "Something went wrong with the platform. Please try again."
  );
}

/** Why a discovered account cannot be linked (3-04), in plain words. */
const UNAVAILABLE_REASONS: Readonly<Record<string, string>> = {
  account_not_enabled: "Cancelled, suspended or closed in Google Ads",
  account_details_missing: "Google did not give its currency or time zone",
  no_account_access: "This Google account cannot read it",
  developer_token_not_approved: "Google has not yet approved AdVegaX for real accounts",
};

export function unavailableReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return UNAVAILABLE_REASONS[reason] ?? "This account cannot be linked";
}

export const JOB_STATUS: Readonly<Record<string, string>> = {
  queued: "Waiting to start",
  running: "In progress",
  succeeded: "Finished",
  failed: "Failed",
  dead: "Failed after several tries",
};
