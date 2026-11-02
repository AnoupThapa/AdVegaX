/**
 * Advertising figures for people (task 3-09). Counts are whole numbers; conversions can be
 * fractional (Google spreads credit), so they keep up to two decimals. Missing values are
 * never shown as 0 (A10): they say why, as everywhere else.
 */

import { AVAILABILITY_LABELS, type Availability } from "@/lib/format/availability";
import { figureReason, roundHalfEven, type Figure } from "@/lib/format/money";

import type { AdFigures } from "./api";
import { numberFormat } from "@/lib/format/number-format";

export function missingText(figures: Pick<AdFigures, "availability" | "reason">): string {
  return figureReason({
    value: null,
    availability: figures.availability as Availability,
    reason: figures.reason ?? null,
  });
}

export function formatCount(value: number | null | undefined, locale?: string): string {
  if (value === null || value === undefined) return AVAILABILITY_LABELS.unavailable;
  return numberFormat(locale).format(value);
}

/** A decimal string with at most two decimals, e.g. "1.5" → "1.5", "3.333333" → "3.33". */
export function formatDecimal(value: string | null | undefined, locale?: string): string {
  if (value === null || value === undefined) return AVAILABILITY_LABELS.unavailable;
  const rounded = roundHalfEven(value, 2);
  if (rounded === null) return AVAILABILITY_LABELS.unavailable;
  return numberFormat(locale, { maximumFractionDigits: 2 }).format(Number(rounded));
}

/** A derived figure that is a plain number (conversion value per amount spent). */
export function formatFigureDecimal(figure: Figure, locale?: string): string {
  if (figure.availability !== "available" || figure.value === null) return figureReason(figure);
  return formatDecimal(figure.value, locale);
}
