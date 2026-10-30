/** Plain-language wording for stores, their sync state, stock and cost (task 2A-10). */

import type { Store } from "./api";

export const STORE_STATUS: Readonly<
  Record<string, { label: string; tone: "ok" | "warn" | "off" }>
> = {
  importing: { label: "Importing", tone: "warn" },
  active: { label: "Up to date", tone: "ok" },
  error: { label: "Problem", tone: "warn" },
  disconnected: { label: "Disconnected", tone: "off" },
};

export function storeStatus(store: Store) {
  if (!store.linked) return { label: "Not linked", tone: "off" as const };
  if (store.connection_status !== "active")
    return { label: "Needs reconnecting", tone: "warn" as const };
  if (store.sync.running && store.status === "active")
    return { label: "Updating", tone: "ok" as const };
  return STORE_STATUS[store.status] ?? { label: store.status, tone: "warn" as const };
}

const SYNC_ERRORS: Readonly<Record<string, string>> = {
  link_ended: "The store was unlinked, so updating stopped.",
  connection_inactive: "The connection is not active. Reconnect it to continue.",
  access_denied: "Shopify refused access to the data. Check the app's permissions.",
  bulk_export_rejected: "Shopify did not accept the data request. Please try again later.",
  download_expired: "The data download expired before it finished. It will be retried.",
  auth_expired: "The platform's permission has expired. Please reconnect.",
  permission_denied: "The platform account does not allow this access.",
  rate_limited: "The platform was busy. It will be retried.",
  server_error: "The platform had a temporary problem. It will be retried.",
  timeout: "The platform took too long to answer. It will be retried.",
  // WooCommerce (2B).
  key_rejected:
    "The store no longer accepts AdVegaX's access key (it was revoked, or the WordPress user was deleted). Reconnect the store.",
  auth_header_stripped:
    "Your web host removes the login details AdVegaX sends. Ask your host to pass the Authorization header through to WordPress.",
  woocommerce_api_not_found:
    "WooCommerce's API is not answering at the store's address. Check that WooCommerce is still active.",
  store_redirected:
    "The store now sends AdVegaX to a different address. Reconnect it with its current address.",
  transport_error: "AdVegaX could not reach the store. It will be retried.",
  unexpected_response: "The store gave an answer AdVegaX could not understand. It will be retried.",
};

/**
 * The daily store check (2B-06): what needs the merchant's attention, with the fix in plain
 * words. Never shown as an error code.
 */
const HEALTH: Readonly<Record<string, { title: string; fix: string }>> = {
  woocommerce_too_old: {
    title: "WooCommerce needs updating",
    fix: "Update WooCommerce to version 9.0 or newer in WordPress (Plugins). Updates continue meanwhile, but some figures may be wrong.",
  },
  timezone_unknown: {
    title: "The store's time zone is not set",
    fix: "In WordPress, open Settings → General and choose a city for the time zone (not a UTC offset), so each day's figures start at your midnight.",
  },
  cost_of_goods_off: {
    title: "Cost not available — switch on Cost of Goods Sold in WooCommerce",
    fix: "In WooCommerce, open Settings → Advanced → Features and switch on Cost of Goods Sold, then enter your product costs. Until then, cost and profit are shown as not available.",
  },
  key_rejected: {
    title: "Needs reconnecting",
    fix: "The store no longer accepts AdVegaX's access key. Reconnect the store on its connection page.",
  },
  auth_header_stripped: {
    title: "Your web host blocks the login details",
    fix: "Ask your host to pass the Authorization header through to WordPress (many hosts have a setting or a support article for this).",
  },
};

const HEALTH_RETRY = {
  title: "The daily check could not finish",
  fix: "AdVegaX could not complete its daily check of the store's settings. It will try again tomorrow; your figures keep updating.",
};

/** The store's health warning as a title and its fix, or null when all is well. */
export function storeHealth(code: string | null | undefined) {
  if (!code) return null;
  return HEALTH[code] ?? HEALTH_RETRY;
}

const COUNTED_STATUS: Readonly<Record<string, string>> = {
  processing: "processing",
  "on-hold": "on hold",
  completed: "completed",
  refunded: "refunded",
};

/** "Counted: …" — which of the platform's order statuses are in the figures (Q-2B-2). */
export function countedStatuses(statuses: readonly string[] | null | undefined): string | null {
  if (!statuses?.length) return null;
  const names = statuses.map((s) => COUNTED_STATUS[s] ?? s);
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
  return `Counted in the figures: ${list} orders. Orders pending payment, failed, cancelled, drafts and trashed orders are not counted.`;
}

export function syncError(code: string | null | undefined): string {
  if (!code) return "";
  return SYNC_ERRORS[code] ?? "Something went wrong while updating this store.";
}

export const SYNC_MODE: Readonly<Record<string, string>> = {
  initial: "First import",
  reconcile: "Checking for changes",
  deep: "Full check",
};

export const PRODUCT_STATUS: Readonly<Record<string, string>> = {
  active: "Active",
  draft: "Draft",
  archived: "Archived",
  unlisted: "Unlisted",
  deleted: "Deleted on the platform",
};

export const COST_SOURCE: Readonly<Record<string, string>> = {
  import_snapshot: "Cost when first imported",
  platform: "Cost from the platform",
};

export const COST_REASON: Readonly<Record<string, string>> = {
  no_cost_from_platform: "No cost on the platform",
  cost_removed: "Cost removed on the platform",
};
