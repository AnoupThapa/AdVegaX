import { numberFormat } from "./number-format";
/**
 * Data availability (A10, PHASE_01C_PLAN §4.8). A value that is not `available` is shown as its
 * state — never as 0 — so missing data can never be mistaken for a real zero.
 */

export type Availability = "available" | "unavailable" | "unsupported" | "not_synchronized";

export const AVAILABILITY_LABELS: Readonly<Record<Exclude<Availability, "available">, string>> = {
  unavailable: "Not available",
  unsupported: "Not supported by this platform",
  not_synchronized: "Not synced yet",
};

export type MetricValue = {
  readonly value: number | string | null;
  readonly availability: Availability;
  /** ISO 4217 code for money values. */
  readonly currency?: string | null;
};

export function formatMetric(metric: MetricValue, locale?: string): string {
  if (metric.availability !== "available" || metric.value === null || metric.value === "") {
    return AVAILABILITY_LABELS[
      metric.availability === "available" ? "unavailable" : metric.availability
    ];
  }
  const number = typeof metric.value === "number" ? metric.value : Number(metric.value);
  if (!Number.isFinite(number)) return AVAILABILITY_LABELS.unavailable;
  return metric.currency
    ? numberFormat(locale, { style: "currency", currency: metric.currency }).format(number)
    : numberFormat(locale).format(number);
}

/** A timestamp, or the right availability label when it has never happened. */
export function formatSyncedAt(value: string | null | undefined, locale?: string): string {
  if (!value) return AVAILABILITY_LABELS.not_synchronized;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}
