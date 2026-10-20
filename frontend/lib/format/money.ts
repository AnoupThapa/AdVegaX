/**
 * Money and ratios from the API (task 2A-10). The API sends exact decimal strings; they are
 * rounded half-even to the currency's minor unit **only here, for display** (PHASE_02A_PLAN §10),
 * using string arithmetic so no value is ever distorted by floating point before rounding.
 */

import { AVAILABILITY_LABELS, type Availability } from "./availability";

const DECIMAL = /^([+-])?(\d+)(?:\.(\d+))?$/;

/** Half-even rounding of a decimal string to `places` digits; `null` if it is not a number. */
export function roundHalfEven(value: string, places: number): string | null {
  const match = DECIMAL.exec(value.trim());
  if (!match) return null;
  const [, sign = "", whole = "0", fraction = ""] = match;
  const kept = fraction.slice(0, places).padEnd(places, "0");
  const rest = fraction.slice(places);
  let digits = BigInt(whole + kept);
  if (rest.length) {
    const first = Number(rest[0]);
    const tail = /[1-9]/.test(rest.slice(1));
    const odd = digits % 2n === 1n;
    if (first > 5 || (first === 5 && (tail || odd))) digits += 1n;
  }
  let text = digits.toString().padStart(places + 1, "0");
  if (places > 0) text = `${text.slice(0, -places)}.${text.slice(-places)}`;
  const negative = sign === "-" && /[1-9]/.test(text);
  return negative ? `-${text}` : text;
}

/** A money amount in its currency, e.g. "A$1,234.50". `null` → "Not available". */
export function formatMoney(
  value: string | null | undefined,
  currency: string,
  minorUnits: number,
  locale?: string,
): string {
  if (value === null || value === undefined) return AVAILABILITY_LABELS.unavailable;
  const rounded = roundHalfEven(value, minorUnits);
  if (rounded === null) return AVAILABILITY_LABELS.unavailable;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: minorUnits,
    maximumFractionDigits: minorUnits,
  }).format(Number(rounded));
}

/** A ratio (0.3 → "30.0%"). */
export function formatRatio(value: string | null | undefined, locale?: string): string {
  if (value === null || value === undefined) return AVAILABILITY_LABELS.unavailable;
  const rounded = roundHalfEven(value, 4);
  if (rounded === null) return AVAILABILITY_LABELS.unavailable;
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(Number(rounded));
}

export type Figure = {
  readonly value: string | null;
  readonly availability: Availability;
  readonly reason?: string | null;
};

const REASONS: Readonly<Record<string, string>> = {
  missing_product_costs: "Some products have no cost",
  no_net_sales: "No net sales in this period",
  not_provided_by_platform: "Not provided by the platform",
  customer_key_not_collected: "Not collected yet",
  not_synchronized: "Not synced yet",
  // Q-2B-5: never added to the store currency until currency conversion (Phase 6).
  other_currency_orders: "Not available — orders in other currencies",
  // Advertising rates (3-09): the divisor was 0, so the rate does not exist.
  no_impressions: "No impressions",
  no_clicks: "No clicks",
  no_conversions: "No conversions",
  no_cost: "No spend",
  not_provided: "Not provided by the platform",
  // Analytics (5-08): rates without sessions, and users, which are counted per day (Q-5-5).
  no_sessions: "No sessions",
  users_per_day_only: "Shown per day only",
};

/** Why a figure is not shown, in plain words. */
export function figureReason(figure: Figure): string {
  if (figure.reason && REASONS[figure.reason]) return REASONS[figure.reason] as string;
  return figure.availability === "available"
    ? ""
    : AVAILABILITY_LABELS[figure.availability as Exclude<Availability, "available">];
}

/** A figure as money, or its availability in words — never a 0 for missing data (A10). */
export function formatFigureMoney(
  figure: Figure,
  currency: string,
  minorUnits: number,
  locale?: string,
): string {
  if (figure.availability !== "available" || figure.value === null) return figureReason(figure);
  return formatMoney(figure.value, currency, minorUnits, locale);
}

export function formatFigureRatio(figure: Figure, locale?: string): string {
  if (figure.availability !== "available" || figure.value === null) return figureReason(figure);
  return formatRatio(figure.value, locale);
}
