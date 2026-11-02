"use client";

import { useState, type ReactNode } from "react";

import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { PERIODS } from "@/features/advertising/Figures";
import type { Organization } from "@/features/organizations/api";
import { useStores } from "@/features/stores/api";
import { addDays, formatDay, todayIn } from "@/features/stores/dates";
import { formatSyncedAt } from "@/lib/format/availability";
import type { Figure } from "@/lib/format/money";

import type { MetricDefinition, Overview } from "./api";
import {
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

/** What every unified-analytics answer carries besides its figures. */
export type Context = Pick<
  Overview,
  | "definition_version"
  | "reporting_currency"
  | "currency_minor_units"
  | "reporting_timezone"
  | "from_day"
  | "to_day"
  | "sources"
  | "conversions"
  | "notes"
  | "definitions"
>;

export const reportingCurrency = (c: Context): ReportingCurrency => ({
  currency: c.reporting_currency,
  minorUnits: c.currency_minor_units,
});

const ALL = "";

/** The period (in the reporting time zone) and, with several stores, the store. */
export function useReportControls(org: Organization): {
  from: string;
  to: string;
  storeId: string | null;
  allStores: boolean;
  toolbar: ReactNode;
} {
  const [period, setPeriod] = useState<string>("30");
  const [store, setStore] = useState<string>(ALL);
  const stores = useStores(org.id);
  const to = todayIn(org.default_timezone);
  const from = addDays(to, -(Number(period) - 1));
  const options = [
    { value: ALL, label: "All stores" },
    ...(stores.data ?? []).map((s) => ({ value: s.id, label: s.name ?? s.domain })),
  ];
  const toolbar = (
    <div className={styles.toolbar}>
      <SelectField
        label="Period"
        options={PERIODS}
        value={period}
        onChange={(event) => setPeriod(event.target.value)}
      />
      {options.length > 2 ? (
        <SelectField
          label="Store"
          options={options}
          value={store}
          onChange={(event) => setStore(event.target.value)}
        />
      ) : null}
    </div>
  );
  return { from, to, storeId: store || null, allStores: store === ALL, toolbar };
}

/** "How is this calculated?" for one figure, from the registry (PLAN §9). */
export function HowCalculated({
  definition,
  withNote = true,
}: {
  definition: MetricDefinition;
  /** False where the note is already shown next to the figure. */
  withNote?: boolean;
}) {
  if (!definition.formula) return null;
  return (
    <details className={own.how}>
      <summary>
        How is this calculated?
        <span className="visually-hidden"> ({definition.label})</span>
      </summary>
      <p>{definition.formula}</p>
      {withNote && definition.note ? <p>{definition.note}</p> : null}
    </details>
  );
}

/** The definitions of a table's columns, under the table. */
export function ColumnDefinitions({
  context,
  keys,
  title = "How these figures are calculated",
}: {
  context: Context;
  keys: readonly string[];
  title?: string;
}) {
  const define = definitionsByKey(context.definitions);
  return (
    <details className={own.how}>
      <summary>{title}</summary>
      <dl className={own.definitions}>
        {keys.map((key) => {
          const d = define(key);
          return (
            <div key={key}>
              <dt>{d.label}</dt>
              <dd>
                {d.formula}
                {d.note ? ` ${d.note}` : ""}
              </dd>
            </div>
          );
        })}
      </dl>
    </details>
  );
}

/** A figure in a table cell, marked when it is missing. */
export function FigureCell({
  figure,
  unit,
  currency,
}: {
  figure: Figure | undefined | null;
  unit: string;
  currency: ReportingCurrency;
}) {
  const missing = !figure || figure.availability !== "available";
  return (
    <td className={`${styles.num} ${missing ? styles.missing : ""}`}>
      {formatFigure(figure ?? undefined, unit, currency)}
    </td>
  );
}

/** Where the numbers come from: each source with its currency, days and freshness. */
export function Sources({ data }: { data: Context }) {
  return (
    <section aria-labelledby="report-sources" className={styles.section}>
      <h2 id="report-sources">Where the numbers come from</h2>
      {data.sources.length === 0 ? (
        <p className={styles.muted}>Nothing is connected for this choice.</p>
      ) : (
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
      )}
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

/** The period line under a heading. */
export function PeriodLine({ data, children }: { data: Context; children?: ReactNode }) {
  return (
    <p className={styles.source}>
      {formatDay(data.from_day)} to {formatDay(data.to_day)}, in {data.reporting_currency}.
      {children ? <> {children}</> : null}
    </p>
  );
}

/** A table that may scroll sideways on narrow screens: focusable so keyboards can scroll it. */
export function ScrollTable({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.tableWrap} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}
