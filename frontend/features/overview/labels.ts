/**
 * Plain words for the unified figures (6-07). Every value comes from the API already
 * calculated; this file only formats it — no page computes a formula (PLAN §13, criterion 5).
 */

import { formatCount, formatDecimal } from "@/features/advertising/format";
import { providerName } from "@/features/advertising/labels";
import { analyticsProviderName } from "@/features/analytics/labels";
import { formatDay } from "@/features/stores/dates";
import {
  figureReason,
  formatFigureMoney,
  formatFigureRatio,
  type Figure,
} from "@/lib/format/money";

import type { Conversion, MetricDefinition, Source } from "./api";

export type ReportingCurrency = { readonly currency: string; readonly minorUnits: number };

/** A figure in its registry unit, or why it is missing — never a 0 for missing data (A10). */
export function formatFigure(
  figure: Figure | undefined,
  unit: string,
  currency: ReportingCurrency,
): string {
  if (!figure) return figureReason({ value: null, availability: "unavailable" });
  if (figure.availability !== "available" || figure.value === null) return figureReason(figure);
  switch (unit) {
    case "money":
      return formatFigureMoney(figure, currency.currency, currency.minorUnits);
    case "ratio":
      return formatFigureRatio(figure);
    case "count":
      return formatCount(Number(figure.value));
    case "multiple":
      return `${formatDecimal(figure.value)}×`;
    default:
      return formatDecimal(figure.value);
  }
}

/** The registry's definitions by key; a missing one falls back to the key itself. */
export function definitionsByKey(definitions: readonly MetricDefinition[]) {
  const map = new Map(definitions.map((d) => [d.key, d]));
  return (key: string): MetricDefinition =>
    map.get(key) ?? { key, label: key, unit: "decimal", formula: "", note: null, sources: [] };
}

/** How the Overview groups the registry's figures (presentation only). */
export const OVERVIEW_GROUPS: ReadonlyArray<{
  readonly id: string;
  readonly title: string;
  readonly keys: readonly string[];
}> = [
  {
    id: "sales",
    title: "Sales and profit",
    keys: ["net_sales", "orders", "product_cost", "gross_profit", "gross_margin"],
  },
  {
    id: "advertising",
    title: "Advertising",
    keys: ["ad_spend", "profit_after_ad_spend", "blended_roas", "cost_per_order", "ad_spend_share"],
  },
  {
    id: "visits",
    title: "Visits (Google Analytics)",
    keys: ["sessions", "analytics_purchases", "analytics_revenue", "store_conversion_rate"],
  },
  {
    id: "not-included",
    title: "Not included yet",
    keys: ["shipping_cost", "payment_fees", "contribution_profit", "customer_acquisition_cost"],
  },
];

/** The columns of the day-by-day table. */
export const DAY_COLUMNS = [
  "net_sales",
  "orders",
  "ad_spend",
  "profit_after_ad_spend",
  "blended_roas",
  "sessions",
] as const;

const STORE_PROVIDERS: Readonly<Record<string, string>> = {
  shopify: "Shopify",
  woocommerce: "WooCommerce",
};

const KINDS: Readonly<Record<string, string>> = {
  store: "Store",
  ad_account: "Ad account",
  analytics_property: "Google Analytics property",
};

export function sourceKind(kind: string): string {
  return KINDS[kind] ?? kind;
}

export function sourceProvider(source: Pick<Source, "kind" | "provider">): string {
  if (source.kind === "store") return STORE_PROVIDERS[source.provider] ?? source.provider;
  if (source.kind === "ad_account") return providerName(source.provider);
  return analyticsProviderName(source.provider);
}

export function sourceName(source: Source): string {
  return source.name ?? `${sourceProvider(source)} ${sourceKind(source.kind).toLowerCase()}`;
}

const RATE_SOURCES: Readonly<Record<string, string>> = {
  ecb: "European Central Bank",
  nrb: "Nepal Rastra Bank",
};

export function rateSources(codes: readonly string[]): string {
  return codes.map((c) => RATE_SOURCES[c] ?? c).join(" and ");
}

/** "Converted from USD with European Central Bank rates published 5 Oct 2026 to 6 Oct 2026." */
export function conversionText(c: Conversion, reporting: string): string {
  const banks = c.rate_sources.length ? ` with ${rateSources(c.rate_sources)} rates` : "";
  let dates = "";
  if (c.first_rate_date && c.last_rate_date) {
    dates =
      c.first_rate_date === c.last_rate_date
        ? ` published ${formatDay(c.first_rate_date)}`
        : ` published ${formatDay(c.first_rate_date)} to ${formatDay(c.last_rate_date)}`;
  }
  const text = `Amounts in ${c.currency} are converted to ${reporting}${banks}${dates}, using each day's rate (weekends and holidays use the last published rate).`;
  if (c.days_without_rate === 0) return text;
  const days = c.days_without_rate === 1 ? "1 day has" : `${c.days_without_rate} days have`;
  return `${text} ${days} no exchange rate, so figures that need ${c.currency} are not available for them.`;
}

export function noteText(note: string, timezone: string): string {
  if (note === "time_zones_differ")
    return `Some sources use a different time zone from your reporting time zone (${timezone.replaceAll("_", " ")}). Each source's figures are counted on its own days, so a day can start a few hours apart between sources.`;
  return note;
}
