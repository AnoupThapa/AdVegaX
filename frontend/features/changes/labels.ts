/** Plain words for the Action Engine's statuses, changes and reasons (Phase 10A). */

import type { Action } from "./api";

type Tone = "ok" | "warn" | "off";

export const ACTION_LABELS: Record<string, string> = {
  "campaign.pause": "Pause the campaign",
  "campaign.resume": "Resume the campaign",
  "campaign.set_daily_budget": "Change the daily budget",
  // Phase 10B: a campaign draft's changes
  "campaign.create": "Create the campaign (paused)",
  "campaign.go_live": "Go live",
  "campaign.remove_draft_objects": "Remove what a failed launch created",
};

const STATUS: Record<string, { label: string; tone: Tone }> = {
  pending: { label: "Waiting for approval", tone: "warn" },
  approved: { label: "Approved", tone: "off" },
  queued: { label: "Approved — waiting to be sent", tone: "off" },
  submitting: { label: "Being sent", tone: "off" },
  unknown: { label: "Checking whether it was made", tone: "warn" },
  succeeded: { label: "Done", tone: "ok" },
  failed: { label: "Not made", tone: "warn" },
  rejected: { label: "Rejected", tone: "warn" },
  cancelled: { label: "Cancelled", tone: "off" },
  stale: { label: "Out of date — not sent", tone: "warn" },
};

export function statusLabel(status: string): { label: string; tone: Tone } {
  return STATUS[status] ?? { label: status, tone: "warn" };
}

export const VERIFICATION: Record<string, string> = {
  verified: "Checked: the platform shows the change.",
  mismatch: "The platform does not show the change as requested. Check the campaign there.",
  not_checked: "Made, but AdVegaX could not read the campaign back to check it.",
};

const REASONS: Record<string, string> = {
  // shape
  daily_budget_required: "Enter the new daily budget.",
  daily_budget_invalid: "Enter a daily budget greater than zero.",
  daily_budget_precision: "The budget has more decimals than the currency allows.",
  unexpected_values: "This change takes no values.",
  max_daily_budget_precision: "The maximum has more decimals than the currency allows.",
  // resource
  platform_cannot_change: "AdVegaX cannot change campaigns on this platform.",
  account_not_linked: "The ad account is not linked to this organization.",
  connection_inactive: "The connection needs attention. Reconnect it first.",
  account_not_active: "The ad account is not active on the platform.",
  campaign_not_changeable: "This campaign can no longer be changed (it is removed or archived).",
  campaign_has_open_change:
    "Another change of this campaign is waiting or being sent. Finish or cancel it first.",
  campaign_unavailable: "The platform could not find this campaign.",
  connection_needs_attention: "The platform refused AdVegaX's sign-in. Reconnect it first.",
  changes_not_allowed:
    "Changes are not allowed for this connection yet. An owner or admin can allow them on the connection's page.",
  permission_missing:
    "The platform has not given AdVegaX permission to make changes. Sign in again and allow changes.",
  // budget
  budget_on_ad_sets:
    "This campaign's budget is set on its ad sets, not on the campaign. Change it in Meta.",
  budget_not_daily: "This campaign has no daily budget of its own (for example a total budget).",
  budget_shared:
    "This budget is shared by several campaigns; changing it would change them all. Change it in Google Ads.",
  no_change: "This is already the campaign's daily budget.",
  // limits
  increase_too_large: "That raises the budget by more than one change allows.",
  decrease_too_large: "That lowers the budget by more than one change allows.",
  below_platform_minimum: "That is below the platform's minimum daily budget.",
  minimum_not_checkable:
    "The platform minimum cannot be checked: no recent exchange rate for this currency.",
  above_maximum: "That is above your organization's maximum daily budget per campaign.",
  maximum_not_checkable:
    "Your maximum cannot be checked: no recent exchange rate between the currencies.",
  maximum_not_set:
    "Choose your organization's maximum daily budget per campaign in Settings before changing budgets.",
  budget_changed_recently: "This campaign's budget was changed less than an hour ago.",
  daily_limit_reached: "This ad account has reached today's number of changes.",
  // state
  already_paused: "The campaign is already paused.",
  already_active: "The campaign is already running.",
  // worker and platform
  campaign_changed:
    "The campaign changed on the platform after this was requested, so nothing was sent. Request it again.",
  outcome_unknown: "The platform did not answer in time. AdVegaX is checking the campaign.",
  not_applied: "The platform did not make the change. You can request it again.",
  changed_elsewhere:
    "The campaign shows something else than both the old and the requested value. Check it on the platform.",
  needs_checking:
    "AdVegaX could not find out whether the change was made. Check the campaign on the platform.",
  request_expired: "Nobody approved this in time.",
  rate_limited: "The platform asked AdVegaX to wait. Request it again later.",
  invalid_request: "The platform refused the change.",
  meta_permission_missing: "Meta refused: AdVegaX lacks the permission to change this account.",
  permission_denied: "The platform refused: no permission to change this account.",
  // campaign builder (10B)
  strategy_not_ready: "Mark the strategy ready first.",
  platform_not_in_strategy: "The strategy does not plan this platform.",
  creative_not_for_this_campaign: "Choose an approved creative of this strategy for this platform.",
  creative_not_approved: "Approve the creative first.",
  image_required: "Choose an image for the Meta creative first.",
  name_invalid: "Give the campaign a name (up to 200 characters).",
  keywords_required: "Add at least one keyword.",
  too_many_keywords: "Use at most 20 keywords.",
  match_type_invalid: "Choose phrase, exact or broad match.",
  keyword_empty: "A keyword is empty.",
  keyword_too_long: "A keyword is longer than 80 characters or 10 words.",
  keyword_characters: "A keyword contains characters Google does not accept (such as ! , ? or *).",
  keyword_duplicate: "A keyword is listed twice.",
  keyword_prohibited: "A keyword contains one of your prohibited words or a health claim.",
  locations_required: "Choose at least one country.",
  location_not_supported: "Choose countries from the list.",
  ages_invalid: "Choose ages between 18 and 65.",
  landing_url_required: "Enter the landing page.",
  landing_url_invalid: "The landing page address is not valid.",
  landing_url_not_https: "The landing page must start with https://.",
  landing_url_not_store:
    "The landing page must be on your store's own web address (add it in Settings if your store uses its own domain).",
  page_required: "Choose the Facebook Page the ad runs as.",
  pixel_invalid: "Choose a pixel from the list.",
  declaration_required: "Confirm the declarations.",
  draft_not_launchable: "This campaign was already launched.",
  draft_not_created: "Create the campaign first.",
  nothing_to_remove: "There is nothing to remove.",
  build_incomplete: "The platform stopped part-way. What was created is paused; you can remove it.",
  platform_unavailable: "The platform could not be reached. Nothing was sent.",
  draft_changed: "The campaign was edited after this was requested. Request it again.",
  incomplete: "Only part of the campaign was created (it is paused). Remove it and launch again.",
  image_unavailable: "The image could not be read. Choose it again.",
  choose_ad_account: "Choose which ad account the campaign is for.",
  no_ad_account: "Link an ad account for this platform first.",
  landing_domain_invalid: "Enter web addresses like evezone.com.au (no https:// or path).",
  developer_token_not_approved:
    "Google allows AdVegaX to change test accounts only, until its access is upgraded.",
};

export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "";
  // Keyword reasons name the line, e.g. "keyword_duplicate:3" (the fourth keyword).
  const [base, index] = reason.split(":");
  const known = REASONS[base ?? ""];
  if (known && index && /^\d+$/.test(index)) return `${known} (keyword ${Number(index) + 1})`;
  return known ?? `The platform refused the change (${reason.replaceAll("_", " ")}).`;
}

export const CHECK_GROUPS: Record<string, string> = {
  shape: "The values",
  creative: "The strategy and creative",
  keywords: "Keywords",
  targeting: "Targeting",
  landing_page: "The landing page",
  meta: "Meta Page and pixel",
  declaration: "Declarations",
  draft: "The campaign draft",
  resource: "The campaign and its account",
  budget: "The budget",
  limits: "Limits",
  state: "The campaign's state",
  dry_run: "The platform's own check",
};

/** What the change does, in words (the amounts come formatted from the caller). */
export function describe(action: Action, money: (value: string) => string): string {
  if (action.draft) {
    return `${ACTION_LABELS[action.action_type]}: ${action.draft.name}`;
  }
  if (action.action_type === "campaign.set_daily_budget") {
    const before = action.previous.daily_budget;
    const after = action.params.daily_budget ?? "";
    return before
      ? `Daily budget from ${money(before)} to ${money(after)}`
      : `Daily budget to ${money(after)}`;
  }
  return ACTION_LABELS[action.action_type] ?? action.action_type;
}
