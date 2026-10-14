"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { SelectField } from "@/components/ui/SelectField";
import { messageFor } from "@/lib/api/errors";
import { AVAILABILITY_LABELS, type Availability } from "@/lib/format/availability";
import {
  figureReason,
  formatFigureMoney,
  formatFigureRatio,
  formatMoney,
  type Figure,
} from "@/lib/format/money";

import { useDailyMetrics, type DailyMetrics, type Store } from "./api";
import { addDays, formatDay, todayIn } from "./dates";
import styles from "./stores.module.css";

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
] as const;

type Totals = DailyMetrics["totals"];
type Money = (value: string | null | undefined) => string;

/** A plain total as a figure carrying the totals' availability. */
const plain = (value: string | null | undefined, availability: Availability): Figure => ({
  value: value ?? null,
  availability,
  reason: availability === "not_synchronized" ? "not_synchronized" : null,
});

function Tile({ label, value, note }: { label: string; value: string; note?: string | undefined }) {
  return (
    <li className={styles.tile}>
      <p className={styles.tileLabel}>{label}</p>
      <p className={styles.tileValue}>{value}</p>
      {note ? <p className={styles.tileNote}>{note}</p> : null}
    </li>
  );
}

function Totals({ totals, money }: { totals: Totals; money: (f: Figure) => string }) {
  const a = totals.availability as Availability;
  const orders =
    totals.orders_count === null || totals.orders_count === undefined
      ? AVAILABILITY_LABELS.not_synchronized
      : new Intl.NumberFormat().format(totals.orders_count);
  const coverage = totals.cost_coverage as Figure;
  return (
    <>
      <ul className={styles.tiles} aria-label="Totals for the period">
        <Tile label="Net sales" value={money(plain(totals.net_sales, a))} />
        <Tile label="Total sales" value={money(plain(totals.total_sales, a))} />
        <Tile label="Orders" value={orders} />
        <Tile
          label="Gross profit"
          value={money(totals.gross_profit as Figure)}
          note={
            totals.gross_profit.availability === "unavailable"
              ? `Cost known for ${formatFigureRatio(coverage)} of net sales`
              : undefined
          }
        />
        <Tile label="Gross margin" value={formatFigureRatio(totals.gross_margin as Figure)} />
        <Tile label="Cost coverage" value={formatFigureRatio(coverage)} />
      </ul>
      <dl className={styles.facts} aria-label="Breakdown">
        <dt>Gross sales</dt>
        <dd>{money(plain(totals.gross_sales, a))}</dd>
        <dt>Discounts</dt>
        <dd>{money(plain(totals.discounts, a))}</dd>
        <dt>Returns and adjustments</dt>
        <dd>{money(plain(totals.sales_reversals, a))}</dd>
        <dt>Shipping charged</dt>
        <dd>{money(plain(totals.shipping, a))}</dd>
        <dt>Taxes</dt>
        <dd>{money(plain(totals.taxes, a))}</dd>
        <dt>Duties</dt>
        <dd>{money(plain(totals.duties, a))}</dd>
        <dt>Fees</dt>
        <dd>{money(plain(totals.fees, a))}</dd>
        <dt>Cost of goods</dt>
        <dd>{money(totals.cogs as Figure)}</dd>
        <dt>Shipping costs</dt>
        <dd>{figureReason(totals.shipping_cost as Figure)}</dd>
        <dt>Payment fees</dt>
        <dd>{figureReason(totals.payment_fees as Figure)}</dd>
        <dt>New vs returning customers</dt>
        <dd>{figureReason(totals.new_vs_returning as Figure)}</dd>
      </dl>
    </>
  );
}

function DailyTable({ data, money }: { data: DailyMetrics; money: Money }) {
  const cell = (value: string | null | undefined, synced: boolean) =>
    synced ? money(value) : AVAILABILITY_LABELS.not_synchronized;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          Each day in the store&apos;s time zone ({data.timezone}). Refunds and returns count on the
          day they were processed.
        </caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col" className={styles.num}>
              Orders
            </th>
            <th scope="col" className={styles.num}>
              Net sales
            </th>
            <th scope="col" className={styles.num}>
              Total sales
            </th>
            <th scope="col" className={styles.num}>
              Cost of goods
            </th>
          </tr>
        </thead>
        <tbody>
          {[...data.days].reverse().map((day) => {
            const synced = day.availability === "available";
            const cogs = day.cogs as Figure;
            return (
              <tr key={day.day}>
                <th scope="row">{formatDay(day.day)}</th>
                <td className={`${styles.num} ${synced ? "" : styles.missing}`}>
                  {synced ? day.orders_count : AVAILABILITY_LABELS.not_synchronized}
                </td>
                <td className={`${styles.num} ${synced ? "" : styles.missing}`}>
                  {cell(day.net_sales, synced)}
                </td>
                <td className={`${styles.num} ${synced ? "" : styles.missing}`}>
                  {cell(day.total_sales, synced)}
                </td>
                <td
                  className={`${styles.num} ${cogs.availability === "available" ? "" : styles.missing}`}
                >
                  {cogs.availability === "available" ? money(cogs.value) : figureReason(cogs)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RevenueView({ orgId, store }: { orgId: string; store: Store }) {
  const [period, setPeriod] = useState<string>("30");
  const to = todayIn(store.timezone);
  const from = addDays(to, -(Number(period) - 1));
  const metrics = useDailyMetrics(orgId, store.id, from, to);
  const money: Money = (value) => formatMoney(value, store.currency, store.currency_minor_units);
  const figureMoney = (figure: Figure) =>
    formatFigureMoney(figure, store.currency, store.currency_minor_units);

  return (
    <section aria-labelledby="revenue-title" className={styles.section}>
      <h2 id="revenue-title">Revenue</h2>
      <div className={styles.toolbar}>
        <SelectField
          label="Period"
          options={PERIODS}
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
        />
      </div>
      {metrics.error ? <Alert tone="error">{messageFor(metrics.error)}</Alert> : null}
      {metrics.isPending ? <p role="status">Loading figures…</p> : null}
      {metrics.data ? (
        <>
          {metrics.data.totals.availability !== "available" ? (
            <Alert tone="info">
              {metrics.data.synced_from
                ? `Part of this period is before ${formatDay(metrics.data.synced_from)}, the first day AdVegaX has complete data for, so period totals are not shown. Choose a shorter period.`
                : "This store's history is still being imported. Figures appear when the import finishes."}
            </Alert>
          ) : null}
          <p className={styles.muted}>
            Amounts in {store.currency}, calculated with definition{" "}
            {metrics.data.definition_version}.
          </p>
          <Totals totals={metrics.data.totals} money={figureMoney} />
          <h3>By day</h3>
          <DailyTable data={metrics.data} money={money} />
        </>
      ) : null}
    </section>
  );
}
