/** Plain-language wording for analytics properties, their sync state and health (5-08). */

import { connectError } from "@/features/connections/labels";

import type { AnalyticsProperty, AnalyticsQuality } from "./api";

export const ANALYTICS_PROVIDERS: Readonly<Record<string, string>> = {
  google_analytics: "Google Analytics",
};

export function analyticsProviderName(code: string): string {
  return ANALYTICS_PROVIDERS[code] ?? code;
}

/** Every figure is the platform's own report (PHASE_05_PLAN §10). */
export function reportedBy(code: string): string {
  return `Reported by ${analyticsProviderName(code)}`;
}

type Tone = "ok" | "warn" | "off";

export function propertyStatus(p: AnalyticsProperty): { label: string; tone: Tone } {
  if (!p.linked) return { label: "Not linked", tone: "off" };
  if (p.connection_status !== "active") return { label: "Needs reconnecting", tone: "warn" };
  if (p.platform_status !== "active") return { label: "Deleted in Google Analytics", tone: "warn" };
  if (p.status === "importing") return { label: "Importing", tone: "warn" };
  if (p.status === "error") return { label: "Problem", tone: "warn" };
  if (p.sync.waiting_for_allowance) return { label: "Waiting", tone: "warn" };
  if (p.sync.running) return { label: "Updating", tone: "ok" };
  if (p.status === "active") return { label: "Up to date", tone: "ok" };
  return { label: p.status, tone: "warn" };
}

export const SYNC_MODE: Readonly<Record<string, string>> = {
  initial: "Importing",
  quick: "Updating today and yesterday",
  nightly: "Re-checking the last 14 days",
  weekly: "Re-checking the last 90 days",
};

const SYNC_ERRORS: Readonly<Record<string, string>> = {
  link_ended: "The property was unlinked, so updating stopped.",
  connection_inactive: "The Google Analytics connection is not active. Reconnect it to continue.",
  no_property_access:
    "The Google account that connected Google Analytics can no longer read this property.",
  property_deleted: "This property was deleted in Google Analytics.",
};

export function analyticsSyncError(code: string | null | undefined): string {
  if (!code) return "";
  return SYNC_ERRORS[code] ?? connectError(code);
}

/** What needs attention on the property, with the fix in plain words (PLAN §6.5). */
const HEALTH: Readonly<Record<string, { title: string; fix: string }>> = {
  no_property_access: {
    title: "You no longer have access to this property",
    fix: "The Google account that connected Google Analytics lost access to it. Ask the property's administrator in Google Analytics to give that Google account at least Viewer access again, then use “Sync now”. Figures already imported stay available.",
  },
  property_deleted: {
    title: "This property was deleted in Google Analytics",
    fix: "AdVegaX cannot read new figures for it. Figures already imported stay available. If it was deleted by mistake, restore it in Google Analytics (Admin → Trash) within 35 days, then use “Sync now”.",
  },
  property_details_changed: {
    title: "Google Analytics reports a different currency or time zone",
    fix: "AdVegaX keeps the currency and time zone it imported, so stored figures stay consistent. Contact AdVegaX support if this property's currency or time zone really changed.",
  },
  rate_limited: {
    title: "Google is limiting how much AdVegaX can read",
    fix: "Figures will update later by themselves. No action is needed.",
  },
};

export function propertyHealth(code: string | null | undefined) {
  if (!code) return null;
  return HEALTH[code] ?? { title: "This property needs attention", fix: analyticsSyncError(code) };
}

/** Google's notes about the figures (Q-5-8): shown, never hidden. */
export function qualityNotes(q: AnalyticsQuality | null | undefined): string[] {
  if (!q) return [];
  const notes: string[] = [];
  if (q.other_row) notes.push("Google grouped some rare values into “(other)”.");
  if (q.thresholded) notes.push("Google withheld some small numbers to protect visitors' privacy.");
  if (q.sampled) notes.push("Google based some figures on a sample of the data.");
  if (q.truncated) notes.push("Not every value could be read, so some may be missing.");
  return notes;
}

export const BREAKDOWNS = [
  { value: "channel", label: "By channel" },
  { value: "source", label: "By source / medium / campaign" },
] as const;
