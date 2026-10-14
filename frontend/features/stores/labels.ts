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
};

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
