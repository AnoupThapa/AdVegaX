"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { Sparkline } from "@/components/ui/Sparkline";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { formatDay } from "@/features/stores/dates";
import { messageFor } from "@/lib/api/errors";
import type { Figure } from "@/lib/format/money";

import { useOverview, type Overview } from "./api";
import own from "./overview.module.css";
import {
  DAY_COLUMNS,
  OVERVIEW_GROUPS,
  definitionsByKey,
  formatFigure,
  type ReportingCurrency,
} from "./labels";
import {
  FigureCell,
  HowCalculated,
  PeriodLine,
  ScrollTable,
  Sources,
  reportingCurrency,
  useReportControls,
} from "./Shared";

/** Figures that read well as a trend over the period; the same numbers are in the table below. */
const TREND_KEYS = new Set(["net_sales", "orders", "ad_spend"]);

function trend(data: Overview, key: string): (number | null)[] {
  return data.days.map((day) => {
    const figure = day.figures[key] as Figure | undefined;
    return figure && figure.availability === "available" && figure.value !== null
      ? Number(figure.value)
      : null;
  });
}

function Tiles({ data, currency }: { data: Overview; currency: ReportingCurrency }) {
  const define = definitionsByKey(data.definitions);
  return (
    <>
      {OVERVIEW_GROUPS.map((group) => (
        <section key={group.id} aria-labelledby={`overview-${group.id}`}>
          <h3 id={`overview-${group.id}`}>{group.title}</h3>
          <ul className={styles.tiles} aria-label={group.title}>
            {group.keys.map((key) => {
              const d = define(key);
              const figure = data.totals[key] as Figure | undefined;
              const missing =
                !figure || figure.availability !== "available" || figure.value === null;
              return (
                <li key={key} className={styles.tile}>
                  <p className={styles.tileLabel}>{d.label}</p>
                  <p className={`${styles.tileValue} ${missing ? styles.tileMissing : ""}`}>
                    {formatFigure(figure, d.unit, currency)}
                  </p>
                  {d.note ? <p className={styles.tileNote}>{d.note}</p> : null}
                  {TREND_KEYS.has(key) && !missing ? (
                    <div className={styles.tileTrend}>
                      <Sparkline values={trend(data, key)} />
                    </div>
                  ) : null}
                  <HowCalculated definition={d} withNote={false} />
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </>
  );
}

function DayTable({ data, currency }: { data: Overview; currency: ReportingCurrency }) {
  const define = definitionsByKey(data.definitions);
  return (
    <ScrollTable label="Figures by day">
      <table className={styles.table}>
        <caption>
          Each day in your reporting time zone ({data.reporting_timezone.replaceAll("_", " ")}),
          newest first. Amounts in {data.reporting_currency}.
        </caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            {DAY_COLUMNS.map((key) => (
              <th key={key} scope="col" className={styles.num}>
                {define(key).label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...data.days].reverse().map((day) => (
            <tr key={day.day}>
              <th scope="row">{formatDay(day.day)}</th>
              {DAY_COLUMNS.map((key) => {
                return (
                  <FigureCell
                    key={key}
                    figure={day.figures[key] as Figure | undefined}
                    unit={define(key).unit}
                    currency={currency}
                  />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  );
}

function Empty({ orgId }: { orgId: string }) {
  return (
    <div className={styles.panel}>
      <h2>Nothing connected yet</h2>
      <p>
        Connect a store, your ad accounts and Google Analytics to see sales, ad spend and profit
        together here.
      </p>
      <p>
        <Link href={`/orgs/${orgId}/connections`}>See connections</Link>
      </p>
    </div>
  );
}

/** The Overview's figures (PLAN §9): tiles, days, sources, conversions and notes. */
export function OverviewFigures({ org }: { org: Organization }) {
  const controls = useReportControls(org);
  const overview = useOverview(org.id, controls.from, controls.to, controls.storeId);

  if (overview.error) return <Alert tone="error">{messageFor(overview.error)}</Alert>;
  if (!overview.data) {
    return (
      <div className={own.loading}>
        <p role="status">Loading figures…</p>
      </div>
    );
  }
  const data = overview.data;
  if (data.sources.length === 0 && controls.allStores) return <Empty orgId={org.id} />;
  const currency = reportingCurrency(data);

  return (
    <>
      <section aria-labelledby="overview-figures" className={styles.section}>
        <h2 id="overview-figures">Sales, ad spend and profit</h2>
        <PeriodLine data={data}>
          Your stores&apos; sales, what Google Ads and Meta report as spent, and Google
          Analytics&apos; visits, put together by AdVegaX.
        </PeriodLine>
        {controls.toolbar}
        <Tiles data={data} currency={currency} />
        <h3>By day</h3>
        <DayTable data={data} currency={currency} />
        <p>
          <Link href={`/orgs/${org.id}/reports`}>See channels, campaigns and products</Link>
        </p>
      </section>
      <Sources data={data} />
    </>
  );
}
