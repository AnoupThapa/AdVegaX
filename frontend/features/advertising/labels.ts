/** Plain-language wording for ad accounts, their sync state and health (task 3-09). */

import { connectError } from "@/features/connections/labels";

import type { AdAccount, AdBudget } from "./api";

/** Whose figures these are: every figure is the platform's own report (PLAN §10). */
export const PROVIDER_NAMES: Readonly<Record<string, string>> = {
  google_ads: "Google Ads",
  meta: "Meta",
};

export function providerName(code: string): string {
  return PROVIDER_NAMES[code] ?? code;
}

export function reportedBy(code: string): string {
  return `Reported by ${providerName(code)}`;
}

type Tone = "ok" | "warn" | "off";

export function adAccountStatus(account: AdAccount): { label: string; tone: Tone } {
  if (!account.linked) return { label: "Not linked", tone: "off" };
  if (account.connection_status !== "active") return { label: "Needs reconnecting", tone: "warn" };
  if (account.platform_status !== "active") return { label: "Not active at Google", tone: "warn" };
  if (account.status === "importing") return { label: "Importing", tone: "warn" };
  if (account.status === "error") return { label: "Problem", tone: "warn" };
  if (account.sync.waiting_for_allowance) return { label: "Waiting", tone: "warn" };
  if (account.sync.running) return { label: "Updating", tone: "ok" };
  if (account.status === "active") return { label: "Up to date", tone: "ok" };
  return { label: account.status, tone: "warn" };
}

export const SYNC_MODE: Readonly<Record<string, string>> = {
  initial: "Importing",
  quick: "Updating recent days",
  nightly: "Re-checking the last 30 days",
  weekly: "Re-checking the last 90 days",
};

const SYNC_ERRORS: Readonly<Record<string, string>> = {
  link_ended: "The ad account was unlinked, so updating stopped.",
  connection_inactive: "The Google Ads connection is not active. Reconnect it to continue.",
};

export function adSyncError(code: string | null | undefined): string {
  if (!code) return "";
  return SYNC_ERRORS[code] ?? connectError(code);
}

/** What needs attention on the account, with the fix in plain words. */
const HEALTH: Readonly<Record<string, { title: string; fix: string }>> = {
  account_not_enabled: {
    title: "This ad account is not active in Google Ads",
    fix: "It is cancelled, suspended or closed, so AdVegaX cannot read new figures. Figures already imported stay available. Reactivate it in Google Ads, then use “Sync now”.",
  },
  no_account_access: {
    title: "AdVegaX can no longer read this ad account",
    fix: "The Google account that connected Google Ads lost access to it. Ask the ad account's administrator to give that Google account access again, then use “Sync now”.",
  },
  developer_token_not_approved: {
    title: "Google has not yet approved AdVegaX for this account",
    fix: "Until Google approves AdVegaX's access level, only test accounts can be read. No action is needed from you.",
  },
  account_details_changed: {
    title: "Google reports a different currency or time zone",
    fix: "AdVegaX keeps the currency and time zone it imported, so stored figures stay consistent. Contact AdVegaX support if this account's currency or time zone really changed.",
  },
};

export function adHealth(code: string | null | undefined) {
  if (!code) return null;
  return (
    HEALTH[code] ?? {
      title: "This ad account needs attention",
      fix: adSyncError(code),
    }
  );
}

export const ENTITY_STATUS: Readonly<Record<string, { label: string; tone: Tone }>> = {
  active: { label: "Active", tone: "ok" },
  paused: { label: "Paused", tone: "off" },
  archived: { label: "Archived", tone: "off" },
  removed: { label: "Removed", tone: "off" },
};

export function entityStatus(status: string) {
  return ENTITY_STATUS[status] ?? { label: status, tone: "warn" as Tone };
}

/** Google's own names for campaign and ad types, made readable ("PERFORMANCE_MAX" → …). */
export function platformType(value: string | null | undefined): string {
  if (!value) return "—";
  const words = value.toLowerCase().split("_").filter(Boolean);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function budgetText(
  budget: AdBudget | null | undefined,
  money: (value: string | null | undefined) => string,
): string {
  if (!budget) return "No budget";
  const amount =
    budget.amount === null || budget.amount === undefined ? null : money(budget.amount);
  const base = amount
    ? budget.period === "daily"
      ? `${amount} a day`
      : `${amount} in total`
    : "Amount not provided";
  return budget.shared ? `${base} (shared)` : base;
}
