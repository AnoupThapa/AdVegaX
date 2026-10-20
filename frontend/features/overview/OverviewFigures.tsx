"use client";

import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { PERIODS } from "@/features/advertising/Figures";
import type { Organization } from "@/features/organizations/api";
import { useStores } from "@/features/stores/api";
import { addDays, formatDay, todayIn } from "@/features/stores/dates";
import { messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";
import type { Figure } from "@/lib/format/money";

import { useOverview, type Overview } from "./api";
import {
  DAY_COLUMNS,
  OVERVIEW_GROUPS,
  conversionText,
  definitionsByKey,
  formatFigure,
  noteText,
  sourceKind,
  sourceName,
  sourceProvider,
  type ReportingCurrency,
} from "./labels";
import own from "./overview.module.css";

const ALL = "";

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
              return (
                <li key={key} className={styles.tile}>
                  <p className={styles.tileLabel}>{d.label}</p>
                  <p className={styles.tileValue}>
                    {formatFigure(data.totals[key] as Figure | undefined, d.unit, currency)}
                  </p>
                  {d.note ? <p className={styles.tileNote}>{d.note}</p> : null}
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
    <div className={styles.tableWrap}>
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
                const figure = day.figures[key] as Figure | undefined;
                const missing = !figure || figure.availability !== "available";
                return (
                  <td key={key} className={`${styles.num} ${missing ? styles.missing : ""}`}>
                    {formatFigure(figure, define(key).unit, currency)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Where the numbers come from: each source with its currency, days and freshness. */
function Sources({ data }: { data: Overview }) {
  return (
    <section aria-labelledby="overview-sources" className={styles.section}>
      <h2 id="overview-sources">Where the numbers come from</h2>
      <ul className={own.sources}>
        {data.sources.map((s) => (
          <li key={`${s.kind}-${s.id}`}>
            <strong>{sourceName(s)}</strong>{" "}
            <span className={styles.muted}>
              {sourceKind(s.kind)} · {sourceProvider(s)} · {s.currency} ·{" "}
              {s.timezone.replaceAll("_", " ")}
            </span>
            <br />
            <span className={styles.muted}>
              {s.synced_from
                ? `Figures from ${formatDay(s.synced_from)}`
                : "Still importing its figures"}
              . Last updated {formatSyncedAt(s.updated_at)}.
            </span>
          </li>
        ))}
      </ul>
      {data.conversions.length || data.notes.length ? (
        <ul className={styles.muted} aria-label="Notes about these figures">
          {data.conversions.map((c) => (
            <li key={c.currency}>{conversionText(c, data.reporting_currency)}</li>
          ))}
          {data.notes.map((n) => (
            <li key={n}>{noteText(n, data.reporting_timezone)}</li>
          ))}
        </ul>
      ) : null}
      <p className={styles.muted}>
        Calculated by AdVegaX with the definitions “{data.definition_version}”.
      </p>
    </section>
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
  const [period, setPeriod] = useState<string>("30");
  const [store, setStore] = useState<string>(ALL);
  const stores = useStores(org.id);
  const to = todayIn(org.default_timezone);
  const from = addDays(to, -(Number(period) - 1));
  const overview = useOverview(org.id, from, to, store || null);
  const storeOptions = [
    { value: ALL, label: "All stores" },
    ...(stores.data ?? []).map((s) => ({ value: s.id, label: s.name ?? s.domain })),
  ];

  if (overview.error) return <Alert tone="error">{messageFor(overview.error)}</Alert>;
  if (!overview.data) return <p role="status">Loading figures…</p>;
  const data = overview.data;
  if (data.sources.length === 0 && store === ALL) return <Empty orgId={org.id} />;
  const currency: ReportingCurrency = {
    currency: data.reporting_currency,
    minorUnits: data.currency_minor_units,
  };

  return (
    <>
      <section aria-labelledby="overview-figures" className={styles.section}>
        <h2 id="overview-figures">Sales, ad spend and profit</h2>
        <p className={styles.source}>
          {formatDay(data.from_day)} to {formatDay(data.to_day)}, in {data.reporting_currency}. Your
          stores&apos; sales, what Google Ads and Meta report as spent, and Google Analytics&apos;
          visits, put together by AdVegaX.
        </p>
        <div className={styles.toolbar}>
          <SelectField
            label="Period"
            options={PERIODS}
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          />
          {storeOptions.length > 2 ? (
            <SelectField
              label="Store"
              options={storeOptions}
              value={store}
              onChange={(event) => setStore(event.target.value)}
            />
          ) : null}
        </div>
        <Tiles data={data} currency={currency} />
        <h3>By day</h3>
        <DayTable data={data} currency={currency} />
      </section>
      <Sources data={data} />
    </>
  );
}
