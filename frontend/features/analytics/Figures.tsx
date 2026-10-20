"use client";

import styles from "@/features/advertising/advertising.module.css";
import {
  formatCount,
  formatDecimal,
  formatFigureDecimal,
  missingText,
} from "@/features/advertising/format";
import { formatDay } from "@/features/stores/dates";
import {
  figureReason,
  formatFigureMoney,
  formatFigureRatio,
  formatMoney,
  type Figure,
} from "@/lib/format/money";

import type { AnalyticsFigures, AnalyticsItem, AnalyticsMetrics } from "./api";
import { qualityNotes } from "./labels";

export type Currency = { readonly currency: string; readonly minorUnits: number };

/** Counts, money and rates of one figures block, each in words when it is missing (A10). */
export function analyticsText(currency: Currency) {
  const available = (f: AnalyticsFigures) => f.availability === "available";
  const count = (f: AnalyticsFigures, value: number | null | undefined) =>
    available(f) ? formatCount(value) : missingText(f);
  return {
    sessions: (f: AnalyticsFigures) => count(f, f.sessions),
    engaged: (f: AnalyticsFigures) => count(f, f.engaged_sessions),
    newUsers: (f: AnalyticsFigures) => count(f, f.new_users),
    purchases: (f: AnalyticsFigures) => count(f, f.purchases),
    keyEvents: (f: AnalyticsFigures) =>
      available(f) ? formatDecimal(f.key_events) : missingText(f),
    revenue: (f: AnalyticsFigures) =>
      available(f)
        ? formatMoney(f.purchase_revenue, currency.currency, currency.minorUnits)
        : missingText(f),
    users: (f: AnalyticsFigures) => {
      const users = f.total_users as Figure;
      if (users.availability !== "available" || users.value === null) return figureReason(users);
      return formatCount(Number(users.value));
    },
    engagementRate: (f: AnalyticsFigures) => formatFigureRatio(f.engagement_rate as Figure),
    conversionRate: (f: AnalyticsFigures) =>
      formatFigureRatio(f.purchase_conversion_rate as Figure),
    keyEventsPerSession: (f: AnalyticsFigures) =>
      formatFigureDecimal(f.key_events_per_session as Figure),
    revenuePerSession: (f: AnalyticsFigures) =>
      formatFigureMoney(f.revenue_per_session as Figure, currency.currency, currency.minorUnits),
  };
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <li className={styles.tile}>
      <p className={styles.tileLabel}>{label}</p>
      <p className={styles.tileValue}>{value}</p>
      {note ? <p className={styles.tileNote}>{note}</p> : null}
    </li>
  );
}

/** The period's totals as tiles, with the rates derived from them. Users are per day only. */
export function AnalyticsTiles({
  figures,
  currency,
  label,
}: {
  figures: AnalyticsFigures;
  currency: Currency;
  label: string;
}) {
  const t = analyticsText(currency);
  return (
    <ul className={styles.tiles} aria-label={label}>
      <Tile label="Sessions" value={t.sessions(figures)} />
      <Tile label="Engaged sessions" value={t.engaged(figures)} />
      <Tile
        label="Users"
        value={t.users(figures)}
        note="A person who visits on two days counts once on each day, so users are never added up."
      />
      <Tile label="New users" value={t.newUsers(figures)} />
      <Tile label="Key events" value={t.keyEvents(figures)} />
      <Tile label="Purchases" value={t.purchases(figures)} />
      <Tile
        label="Purchase revenue"
        value={t.revenue(figures)}
        note="Purchases minus refunds, as Google Analytics reports it."
      />
      <Tile label="Engagement rate" value={t.engagementRate(figures)} />
      <Tile label="Purchase conversion rate" value={t.conversionRate(figures)} />
      <Tile label="Key events per session" value={t.keyEventsPerSession(figures)} />
      <Tile label="Revenue per session" value={t.revenuePerSession(figures)} />
    </ul>
  );
}

function Notes({ figures }: { figures: AnalyticsFigures }) {
  const notes = qualityNotes(figures.quality);
  if (notes.length === 0) return null;
  return <span className={styles.muted}>{notes.join(" ")}</span>;
}

/** The property's days, newest first; the last days are marked as still being processed. */
export function AnalyticsDailyTable({
  data,
  currency,
}: {
  data: AnalyticsMetrics;
  currency: Currency;
}) {
  const t = analyticsText(currency);
  const cell = (missing: boolean) => `${styles.num} ${missing ? styles.missing : ""}`;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          Each day in the property&apos;s time zone ({data.timezone}). Days marked “still being
          processed” can still change in Google Analytics.
        </caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col" className={styles.num}>
              Sessions
            </th>
            <th scope="col" className={styles.num}>
              Users
            </th>
            <th scope="col" className={styles.num}>
              Key events
            </th>
            <th scope="col" className={styles.num}>
              Purchases
            </th>
            <th scope="col" className={styles.num}>
              Purchase revenue
            </th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {[...data.days].reverse().map((day) => {
            const missing = day.availability !== "available";
            return (
              <tr key={day.day}>
                <th scope="row">
                  {formatDay(day.day)}
                  {day.processing && !missing ? (
                    <span className={styles.unsettled}>still being processed</span>
                  ) : null}
                </th>
                <td className={cell(missing)}>{t.sessions(day)}</td>
                <td className={cell(missing)}>{t.users(day)}</td>
                <td className={cell(missing)}>{t.keyEvents(day)}</td>
                <td className={cell(missing)}>{t.purchases(day)}</td>
                <td className={cell(missing)}>{t.revenue(day)}</td>
                <td>
                  <Notes figures={day} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function itemName(item: AnalyticsItem): string {
  if (item.channel_group) return item.channel_group;
  return [item.source, item.medium].filter(Boolean).join(" / ");
}

/** A channel, or a source / medium / campaign, with its own figures for the period. */
export function BreakdownTable({ data, currency }: { data: AnalyticsMetrics; currency: Currency }) {
  const t = analyticsText(currency);
  const bySource = data.breakdown === "source";
  if (data.items.length === 0) return <p>No visits in this period.</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          {bySource ? "Sources, mediums and campaigns" : "Channels"} with their own figures for the
          period, most sessions first. Users are shown per day only, so they are not listed for a
          period.
          {data.item_count > data.items.length
            ? ` Showing the ${data.items.length} largest of ${data.item_count}.`
            : ""}
        </caption>
        <thead>
          <tr>
            <th scope="col">{bySource ? "Source / medium" : "Channel"}</th>
            {bySource ? <th scope="col">Campaign</th> : null}
            <th scope="col" className={styles.num}>
              Sessions
            </th>
            <th scope="col" className={styles.num}>
              Engagement rate
            </th>
            <th scope="col" className={styles.num}>
              Key events
            </th>
            <th scope="col" className={styles.num}>
              Purchases
            </th>
            <th scope="col" className={styles.num}>
              Purchase revenue
            </th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((item) => (
            <tr key={item.key}>
              <th scope="row">{itemName(item)}</th>
              {bySource ? <td>{item.campaign}</td> : null}
              <td className={styles.num}>{t.sessions(item.figures)}</td>
              <td className={styles.num}>{t.engagementRate(item.figures)}</td>
              <td className={styles.num}>{t.keyEvents(item.figures)}</td>
              <td className={styles.num}>{t.purchases(item.figures)}</td>
              <td className={styles.num}>{t.revenue(item.figures)}</td>
              <td>
                <Notes figures={item.figures} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
