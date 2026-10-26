/** Words for the campaign strategies (Phase 8, 8-06). Codes come from the API (§19H). */

import { providerName } from "@/features/advertising/labels";

export const PLATFORMS = ["google_ads", "meta_ads"] as const;

export const OBJECTIVES: Readonly<Record<string, string>> = {
  sales: "Sales",
  leads: "Leads",
  awareness: "Awareness",
};

export const CAMPAIGN_TYPES: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  google_ads: { search: "Search", performance_max: "Performance Max", shopping: "Shopping" },
  meta_ads: { advantage_plus_shopping: "Advantage+ shopping", sales: "Sales" },
};

export function campaignType(platform: string, code: string): string {
  return CAMPAIGN_TYPES[platform]?.[code] ?? code;
}

export const STATUS: Readonly<Record<string, { label: string; tone: "ok" | "warn" | "off" }>> = {
  draft: { label: "Draft", tone: "warn" },
  ready: { label: "Ready for the campaign builder", tone: "ok" },
  archived: { label: "Archived", tone: "off" },
};

export const statusLabel = (code: string) => STATUS[code]?.label ?? code;

/** Target metrics and how their range is shown (money in the reporting currency). */
export const TARGETS: Readonly<Record<string, { label: string; unit: "money" | "multiple" }>> = {
  roas: { label: "Return on ad spend (ROAS)", unit: "multiple" },
  cost_per_order: { label: "Cost per order", unit: "money" },
  cost_per_click: { label: "Cost per click", unit: "money" },
  cost_per_conversion: { label: "Cost per conversion", unit: "money" },
};

export const RISKS: Readonly<Record<string, string>> = {
  margin_unknown: "Margin unknown",
  margin_negative: "No margin",
  low_stock: "Low stock",
  limited_history: "Little history",
  tracking_gap: "Tracking gap",
  competition: "Competition",
  seasonality: "Seasonality",
  other: "Other",
};

export const PERIODS: Readonly<Record<string, string>> = { daily: "per day", monthly: "per month" };

/** Why a request or an answer was refused, in plain words (the API's reason codes). */
const REASONS: Readonly<Record<string, (detail: string) => string>> = {
  product_not_active: () => "The product is not active in your store.",
  out_of_stock: () => "The product is out of stock.",
  no_ad_platform: () => "No ad platform is connected for this product's store.",
  platform_not_connected: (p) => `${providerName(p)} is not connected for this product's store.`,
  budget_too_small: () =>
    "The budget is below the minimum daily budget of the platforms you chose together.",
  budget_minimum_not_checkable: () =>
    "The platforms' minimum budgets could not be checked yet (no exchange rate). Try again later.",
  below_platform_minimum: (p) =>
    `The amount for ${providerName(p)} is below its minimum daily budget.`,
  shares_do_not_add_up: () => "The budget shares do not add up to 100%.",
  share_invalid: (p) =>
    `The budget share for ${providerName(p)} must be more than 0% and at most 100%, with at most two decimals.`,
  unknown_evidence: (k) => `It cited a figure AdVegaX does not have (${k}).`,
  evidence_not_available: (k) => `It relied on a figure AdVegaX does not have yet (${k}).`,
  risk_missing: (r) => `It must name this risk: ${RISKS[r] ?? r}.`,
  target_outside_history: (t) =>
    `The ${TARGETS[t]?.label.toLowerCase() ?? t} target is far from this business's own results.`,
  target_range_invalid: (t) =>
    `The ${TARGETS[t]?.label.toLowerCase() ?? t} target needs a low value no higher than its high value.`,
  duplicate_target: (t) => `The ${TARGETS[t]?.label.toLowerCase() ?? t} target is given twice.`,
  platform_not_requested: (p) => `It planned ${providerName(p)}, which was not chosen.`,
  platform_missing: (p) => `It left out ${providerName(p)}.`,
  duplicate_platform: (p) => `${p ? providerName(p) : "A platform"} is listed twice.`,
  campaign_type_not_for_platform: (p) => `That campaign type does not exist on ${providerName(p)}.`,
  objective_not_requested: () => "It chose a different objective from the one you asked for.",
  answer_not_json: () => "The AI's answer was not in the expected form.",
  answer_refused: () => "The AI declined to answer.",
  answer_too_long: () => "The AI's answer was cut off.",
  too_long: (f) => `A text is too long (${f}).`,
  too_many: (f) => `There are too many entries (${f}).`,
  empty: (f) => `Something is empty (${f}).`,
  invalid_text: (f) => `A text contains characters that are not allowed (${f}).`,
  shape: (f) => `Something is missing or has the wrong form (${f}).`,
  unknown_value: (f) => `A value is not one of the allowed choices (${f}).`,
  too_many_decimals: () => "The budget has more decimals than the currency allows.",
};

export function reasonText(code: string): string {
  const [base = code, detail = ""] = code.split(/:(.*)/s);
  const words = REASONS[base];
  return words ? words(detail) : `It did not pass a check (${code}).`;
}

/** The reasons an API error carries (`details[].reason` or `details[].issue`). */
export function errorReasons(
  details: ReadonlyArray<{ reason?: string; issue?: string }>,
): string[] {
  return [
    ...new Set(details.map((d) => d.reason ?? d.issue).filter((r): r is string => Boolean(r))),
  ].map(reasonText);
}
