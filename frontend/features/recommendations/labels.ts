/** Plain words for recommendations (Phase 11). */

export const KIND_LABELS: Record<string, string> = {
  spend_without_results: "Spend without results",
  losing_money: "Losing money",
  budget_limited: "Held back by its budget",
  cost_jump: "Cost per conversion jumped",
  funnel_drop: "Drop in the funnel",
};

export type Tone = "ok" | "warn" | "off";

export const STATUS_LABELS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "Open", tone: "warn" },
  approved: { label: "Approved", tone: "ok" },
  rejected: { label: "Rejected", tone: "off" },
  done: { label: "Looked into", tone: "ok" },
  expired: { label: "Expired", tone: "off" },
  out_of_date: { label: "Out of date", tone: "off" },
  superseded: { label: "Replaced", tone: "off" },
};

export const CONFIDENCE_LABELS: Record<string, string> = {
  low: "Low confidence",
  medium: "Medium confidence",
  high: "High confidence",
};

export const REJECT_REASONS = [
  { value: "not_relevant", label: "Not relevant for this campaign" },
  { value: "figures_wrong", label: "I disagree with the figures" },
  { value: "wrong_time", label: "Not now" },
  { value: "other", label: "Another reason" },
] as const;

export const FIGURE_LABELS: Record<string, string> = {
  spend: "Spend",
  conversions: "Conversions (platform)",
  conversion_value: "Conversion value (platform)",
  value_per_spend: "Conversion value per 1 spent",
  cost_per_conversion: "Cost per conversion",
  budget_use: "Daily budget used",
  baseline_conversions: "Conversions in the days before",
  baseline_cost_per_conversion: "Cost per conversion in the days before",
  gross_margin: "Your gross margin",
  break_even: "Needed to break even (per 1 spent)",
  cost_increase: "Increase in cost per conversion",
  rate: "Rate in the period",
  previous_rate: "Rate in the period before",
  baseline_rate: "Usual rate",
  fall: "Fall",
};

export const CLOSED_REASONS: Record<string, string> = {
  campaign_changed: "The campaign's status or budget changed since this advice.",
  no_longer_true: "With the latest figures, the rule no longer applies.",
  replaced: "A newer look replaced it.",
};

export const PROFIT_REASONS: Record<string, string> = {
  no_store: "no store is connected",
  no_sales: "there were no sales in these days",
  costs_missing: "product costs are missing for too many sales",
  no_margin: "the gross margin is zero or negative",
  not_synced: "the store's figures are not complete yet",
};

export const AI_PROBLEMS: Record<string, string> = {
  ai_unavailable: "the AI is not set up",
  ai_limit_reached: "today's AI limit was reached",
  ai_answer_rejected: "the AI's answer did not pass AdVegaX's checks",
};

export const NOTE_TEXT: Record<string, string> = {
  budget_on_ad_sets: "Its budget is set on its ad sets, not on the campaign.",
  budget_not_daily: "It has no daily budget AdVegaX can change.",
  budget_shared: "Its budget is shared with other campaigns.",
  at_maximum: "Its budget is already at your maximum daily budget.",
  at_minimum: "Its budget is already at the platform's minimum.",
  no_change: "The change would be too small.",
};

export const kindLabel = (kind: string) => KIND_LABELS[kind] ?? kind;
export const statusOf = (status: string): { label: string; tone: Tone } =>
  STATUS_LABELS[status] ?? { label: status, tone: "off" };
