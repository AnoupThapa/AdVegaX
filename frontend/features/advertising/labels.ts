/** Plain-language wording for ad accounts, their sync state and health (3-09; Meta 4-07). */

import { connectError } from "@/features/connections/labels";

export { signInNotice } from "@/features/connections/labels";

import type { AdAccount, AdBudget } from "./api";

/** Whose figures these are: every figure is the platform's own report (PLAN §10). */
export const PROVIDER_NAMES: Readonly<Record<string, string>> = {
  google_ads: "Google Ads",
  meta_ads: "Meta",
};

export function providerName(code: string): string {
  return PROVIDER_NAMES[code] ?? code;
}

export function reportedBy(code: string): string {
  return `Reported by ${providerName(code)}`;
}

/** Each platform's own words for the same things (PHASE_04_PLAN §12). */
export type PlatformWords = {
  readonly name: string;
  readonly adGroup: string;
  readonly adGroups: string;
  readonly clicks: string;
  readonly conversions: string;
  readonly conversionValue: string;
  readonly costPerConversion: string;
  readonly signInAccount: string;
  readonly conversionsNote: string | null;
};

const GOOGLE_WORDS: PlatformWords = {
  name: "Google Ads",
  adGroup: "ad group",
  adGroups: "ad groups",
  clicks: "Clicks",
  conversions: "Conversions",
  conversionValue: "Conversion value",
  costPerConversion: "Cost per conversion",
  signInAccount: "Google account",
  conversionsNote: null,
};

const META_WORDS: PlatformWords = {
  name: "Meta",
  adGroup: "ad set",
  adGroups: "ad sets",
  clicks: "Link clicks",
  conversions: "Purchases",
  conversionValue: "Purchase value",
  costPerConversion: "Cost per purchase",
  signInAccount: "Facebook account",
  conversionsNote:
    "Purchases are Meta's website, app and offline purchases, counted with each ad set's own attribution setting, as in Ads Manager. They need the Meta Pixel or Conversions API to be set up.",
};

export function platformWords(code: string | null | undefined): PlatformWords {
  if (code === "meta_ads") return META_WORDS;
  if (code === "google_ads" || !code) return GOOGLE_WORDS;
  return { ...GOOGLE_WORDS, name: providerName(code) };
}

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type Tone = "ok" | "warn" | "off";

export function adAccountStatus(account: AdAccount): { label: string; tone: Tone } {
  if (!account.linked) return { label: "Not linked", tone: "off" };
  if (account.connection_status !== "active") return { label: "Needs reconnecting", tone: "warn" };
  if (account.platform_status !== "active")
    return { label: `Not active at ${platformWords(account.provider).name}`, tone: "warn" };
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

function syncErrors(provider: string | null | undefined): Readonly<Record<string, string>> {
  const name = platformWords(provider).name;
  return {
    link_ended: "The ad account was unlinked, so updating stopped.",
    connection_inactive: `The ${name} connection is not active. Reconnect it to continue.`,
    quota_waiting: `${name} is limiting how much AdVegaX can read right now. Figures update by themselves later.`,
  };
}

export function adSyncError(code: string | null | undefined, provider?: string | null): string {
  if (!code) return "";
  return syncErrors(provider)[code] ?? connectError(code);
}

/** What needs attention on the account, with the fix in plain words. */
function healthFor(
  provider: string | null | undefined,
): Record<string, { title: string; fix: string }> {
  const w = platformWords(provider);
  const common = {
    no_account_access: {
      title: "AdVegaX can no longer read this ad account",
      fix: `The ${w.signInAccount} that connected ${w.name} lost access to it. Ask the ad account's administrator to give that ${w.signInAccount} access again, then use “Sync now”.`,
    },
    account_details_changed: {
      title: `${w.name} reports a different currency or time zone`,
      fix: "AdVegaX keeps the currency and time zone it imported, so stored figures stay consistent. Contact AdVegaX support if this account's currency or time zone really changed.",
    },
  };
  if (provider === "meta_ads") {
    return {
      ...common,
      account_not_enabled: {
        title: "Meta disabled or closed this ad account",
        fix: "AdVegaX cannot read new figures while it is disabled or closed. Figures already imported stay available. Once it is active again in Meta, use “Sync now”.",
      },
      account_unsettled: {
        title: "The ad account has an unpaid balance in Meta",
        fix: "Meta stops the account until the balance is paid. Settle it in Meta's billing settings, then use “Sync now”. Figures already imported stay available.",
      },
      account_under_review: {
        title: "Meta is reviewing this ad account",
        fix: "Meta pauses accounts during a review. No action is needed in AdVegaX: once Meta finishes, use “Sync now”.",
      },
      rate_limited: {
        title: "Meta is limiting how much AdVegaX can read",
        fix: "Figures will update later by themselves. No action is needed.",
      },
    };
  }
  return {
    ...common,
    account_not_enabled: {
      title: "This ad account is not active in Google Ads",
      fix: "It is cancelled, suspended or closed, so AdVegaX cannot read new figures. Figures already imported stay available. Reactivate it in Google Ads, then use “Sync now”.",
    },
    developer_token_not_approved: {
      title: "Google has not yet approved AdVegaX for this account",
      fix: "Until Google approves AdVegaX's access level, only test accounts can be read. No action is needed from you.",
    },
  };
}

export function adHealth(code: string | null | undefined, provider?: string | null) {
  if (!code) return null;
  return (
    healthFor(provider)[code] ?? {
      title: "This ad account needs attention",
      fix: adSyncError(code, provider),
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

/** The platform's own names for types and goals, made readable ("PERFORMANCE_MAX",
 * "OUTCOME_SALES" → …). */
export function platformType(value: string | null | undefined): string {
  if (!value) return "—";
  const words = value
    .replace(/^OUTCOME_/, "")
    .toLowerCase()
    .split("_")
    .filter(Boolean);
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
