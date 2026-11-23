/** Words for the creative engine (Phase 9, 9-06). Codes come from the API (§19I). */

export const CREATIVE_STATUS: Readonly<
  Record<string, { label: string; tone: "ok" | "warn" | "off" }>
> = {
  draft: { label: "Draft", tone: "warn" },
  approved: { label: "Approved", tone: "ok" },
  rejected: { label: "Rejected", tone: "off" },
  archived: { label: "Archived", tone: "off" },
};

export const CALLS_TO_ACTION: Readonly<Record<string, string>> = {
  SHOP_NOW: "Shop now",
  LEARN_MORE: "Learn more",
  ORDER_NOW: "Order now",
  GET_QUOTE: "Get quote",
  CONTACT_US: "Contact us",
  SIGN_UP: "Sign up",
};

const FIELDS: Readonly<Record<string, string>> = {
  headlines: "Headline",
  descriptions: "Description",
  primary_texts: "Primary text",
  path1: "Display path 1",
  path2: "Display path 2",
  call_to_action: "Call to action",
  content: "The ad",
};

/** "headlines[2]" → "Headline 3". */
export function fieldLabel(field: string): string {
  const match = /^(\w+)\[(\d+)\]$/.exec(field);
  if (match) return `${FIELDS[match[1] ?? ""] ?? match[1]} ${Number(match[2]) + 1}`;
  return FIELDS[field] ?? field;
}

const CHECKS: Readonly<Record<string, (detail: string | null) => string>> = {
  too_long: (d) => `is longer than ${d ?? "the limit"} characters`,
  too_few: (d) => `needs at least ${d ?? "more"} lines`,
  too_many: (d) => `may have at most ${d ?? "fewer"} lines`,
  empty: () => "is empty",
  duplicate: () => "repeats another line",
  invalid_path: () => "must be one word (letters, digits or hyphens)",
  unknown_value: () => "is not one of the allowed choices",
  shape: () => "is missing or has the wrong form",
  invalid_text: () => "contains characters that are not allowed",
  phone_number: () => "contains a phone number (not allowed in Google Ads text)",
  email_address: () => "contains an e-mail address (not allowed in Google Ads text)",
  web_address: () => "contains a web address (not allowed in Google Ads text)",
  emoji: () => "contains an emoji (not allowed in Google Ads text)",
  all_caps: (d) =>
    `has a word in capitals${d ? ` (${d})` : ""} — add it to your allowed words if it is a brand`,
  repeated_punctuation: () => 'repeats "!" or "?"',
  prohibited_term: (d) => `uses a prohibited claim${d ? `: "${d}"` : ""}`,
  price_not_in_catalogue: (d) =>
    `states a price${d ? ` (${d})` : ""} that is not one of the product's prices`,
  superlative: (d) => `makes a superlative claim${d ? ` ("${d}")` : ""} — check you can support it`,
};

/** One check's result in plain words, e.g. "Headline 3 is longer than 30 characters." */
export function checkText(check: { code: string; field: string; detail?: string | null }): string {
  const words = CHECKS[check.code];
  const what = words ? words(check.detail ?? null) : `did not pass a check (${check.code})`;
  return `${fieldLabel(check.field)} ${what}.`;
}

/** The planner's rejection reasons for creatives, e.g. "google_ads[0].too_long:headlines[2]=30". */
export function creativeReasonText(reason: string): string | null {
  const match = /^(google_ads|meta_ads)\[(\d+)\]\.(\w+):([\w[\]]+)(?:=(.*))?$/.exec(reason);
  if (!match) return null;
  const [, platform, index, code = "", field = "", detail] = match;
  const where = `${platform === "google_ads" ? "Google Ads" : "Meta"} concept ${Number(index) + 1}`;
  return `${where}: ${checkText({ code, field, detail: detail ?? null })}`;
}

export const ASSET_REASONS: Readonly<Record<string, string>> = {
  not_an_image: "The file is not a picture AdVegaX can read.",
  unsupported_type: "Use a JPEG, PNG or WebP picture.",
  too_small: "The picture is too small: at least 600 × 600 pixels.",
  too_large: "The file is too large: at most 10 MB.",
  too_many_pixels: "The picture has too many pixels.",
  empty: "The file is empty.",
};
