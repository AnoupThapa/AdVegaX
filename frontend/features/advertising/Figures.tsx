"use client";

import { formatDay } from "@/features/stores/dates";
import { formatFigureMoney, formatFigureRatio, formatMoney, type Figure } from "@/lib/format/money";

import type { AdDailyMetrics, AdFigures } from "./api";
import styles from "./advertising.module.css";
import { formatCount, formatDecimal, formatFigureDecimal, missingText } from "./format";
import { platformWords, type PlatformWords } from "./labels";

export type Currency = { readonly currency: string; readonly minorUnits: number };

export const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
] as const;

/** Money, counts and rates of one figures block, each in words when it is missing (A10). */
export function figureText(currency: Currency) {
  const money = (value: string | null | undefined) =>
    formatMoney(value, currency.currency, currency.minorUnits);
  return {
    money,
    cost: (f: AdFigures) => (f.availability === "available" ? money(f.cost) : missingText(f)),
    value: (f: AdFigures) =>
      f.availability === "available" ? money(f.conversion_value) : missingText(f),
    impressions: (f: AdFigures) =>
      f.availability === "available" ? formatCount(f.impressions) : missingText(f),
    clicks: (f: AdFigures) =>
      f.availability === "available" ? formatCount(f.clicks) : missingText(f),
    conversions: (f: AdFigures) =>
      f.availability === "available" ? formatDecimal(f.conversions) : missingText(f),
    ctr: (f: AdFigures) => formatFigureRatio(f.click_through_rate as Figure),
    cpc: (f: AdFigures) =>
      formatFigureMoney(f.cost_per_click as Figure, currency.currency, currency.minorUnits),
    cpa: (f: AdFigures) =>
      formatFigureMoney(f.cost_per_conversion as Figure, currency.currency, currency.minorUnits),
    roas: (f: AdFigures) => formatFigureDecimal(f.conversion_value_per_cost as Figure),
  };
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <li className={styles.tile}>
      <p className={styles.tileLabel}>{label}</p>
      <p className={styles.tileValue}>{value}</p>
    </li>
  );
}

/** The period's totals as tiles, with the rates derived from them. */
export function FigureTiles({
  figures,
  currency,
  label,
  words = platformWords(null),
}: {
  figures: AdFigures;
  currency: Currency;
  label: string;
  words?: PlatformWords;
}) {
  const t = figureText(currency);
  return (
    <ul className={styles.tiles} aria-label={label}>
      <Tile label="Spend" value={t.cost(figures)} />
      <Tile label={words.clicks} value={t.clicks(figures)} />
      <Tile label="Impressions" value={t.impressions(figures)} />
      <Tile label={words.conversions} value={t.conversions(figures)} />
      <Tile label={words.conversionValue} value={t.value(figures)} />
      <Tile label="Click-through rate" value={t.ctr(figures)} />
      <Tile label="Cost per click" value={t.cpc(figures)} />
      <Tile label={words.costPerConversion} value={t.cpa(figures)} />
      <Tile
        label={`${words.conversionValue} per ${currency.currency} spent`}
        value={t.roas(figures)}
      />
    </ul>
  );
}

/** Account-level days, newest first; the last days are marked as possibly still changing. */
export function DailyTable({
  data,
  currency,
  words = platformWords(null),
}: {
  data: AdDailyMetrics;
  currency: Currency;
  words?: PlatformWords;
}) {
  const t = figureText(currency);
  const cell = (missing: boolean) => `${styles.num} ${missing ? styles.missing : ""}`;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          Each day in the ad account&apos;s time zone ({data.timezone}). Days marked “may still
          change” can still be corrected by {words.name}.
        </caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col" className={styles.num}>
              Spend
            </th>
            <th scope="col" className={styles.num}>
              {words.clicks}
            </th>
            <th scope="col" className={styles.num}>
              Impressions
            </th>
            <th scope="col" className={styles.num}>
              {words.conversions}
            </th>
            <th scope="col" className={styles.num}>
              {words.conversionValue}
            </th>
          </tr>
        </thead>
        <tbody>
          {[...data.days].reverse().map((day) => {
            const missing = day.availability !== "available";
            return (
              <tr key={day.day}>
                <th scope="row">
                  {formatDay(day.day)}
                  {!day.settled && !missing ? (
                    <span className={styles.unsettled}>may still change</span>
                  ) : null}
                </th>
                <td className={cell(missing)}>{t.cost(day)}</td>
                <td className={cell(missing)}>{t.clicks(day)}</td>
                <td className={cell(missing)}>{t.impressions(day)}</td>
                <td className={cell(missing)}>{t.conversions(day)}</td>
                <td className={cell(missing)}>{t.value(day)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
