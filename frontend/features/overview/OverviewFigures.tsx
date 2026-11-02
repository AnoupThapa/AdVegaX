"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { Sparkline } from "@/components/ui/Sparkline";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { formatDay } from "@/features/stores/dates";
import { messageFor } from "@/lib/api/errors";
import { figureReason, type Figure } from "@/lib/format/money";

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

/** Why figures are missing, each reason once, with where to fix it (a statement's footnotes). */
const FIXES: Readonly<Record<string, { readonly label: string; readonly path: string }>> = {
  missing_product_costs: { label: "Add product costs in Stores", path: "/stores" },
  not_synchronized: { label: "Check Connections", path: "/connections" },
  no_store: { label: "Connect a store", path: "/connections" },
  no_ad_account: { label: "Connect an ad account", path: "/connections" },
  no_analytics_property: { label: "Connect Google Analytics", path: "/connections" },
};

type Note = { readonly key: string; readonly text: string; readonly number: number };

function missingOf(figure: Figure | undefined): boolean {
  return !figure || figure.availability !== "available" || figure.value === null;
}

function notesFor(data: Overview): Map<string, Note> {
  const notes = new Map<string, Note>();
  // "Not included yet" is missing by design (said in its own rows), so it gets no footnote.
  for (const group of OVERVIEW_GROUPS.filter((g) => g.id !== "not-included")) {
    for (const key of group.keys) {
      const figure = data.totals[key] as Figure | undefined;
      if (!missingOf(figure)) continue;
      const reasonKey = figure?.reason ?? figure?.availability ?? "unavailable";
      if (!notes.has(reasonKey)) {
        const text = figure ? figureReason(figure) : "Not available";
        notes.set(reasonKey, { key: reasonKey, text, number: notes.size + 1 });
      }
    }
  }
  return notes;
}

function noteOf(notes: Map<string, Note>, figure: Figure | undefined): Note | undefined {
  return notes.get(figure?.reason ?? figure?.availability ?? "unavailable");
}

/** One sentence built from the period's own figures: what was sold, spent and kept. */
function Statement({
  org,
  data,
  currency,
}: {
  org: Organization;
  data: Overview;
  currency: ReportingCurrency;
}) {
  const define = definitionsByKey(data.definitions);
  const show = (key: string) => {
    const figure = data.totals[key] as Figure | undefined;
    return missingOf(figure) ? null : formatFigure(figure, define(key).unit, currency);
  };
  const sales = show("net_sales");
  const orders = show("orders");
  const spend = show("ad_spend");
  const profit = show("profit_after_ad_spend");
  return (
    <p className={own.statement}>
      {org.name}{" "}
      {sales ? (
        <>
          sold <strong data-figure>{sales}</strong>
          {orders ? (
            <>
              {" "}
              in <strong data-figure>{orders}</strong> {orders === "1" ? "order" : "orders"}
            </>
          ) : null}
        </>
      ) : (
        <>has no sales figure yet</>
      )}
      {spend ? (
        <>
          , and spent <strong data-figure>{spend}</strong> on ads.
        </>
      ) : (
        <>, and its ad spend is not in yet.</>
      )}{" "}
      {profit ? (
        <>
          After ad spend, it kept <strong data-figure>{profit}</strong>.
        </>
      ) : (
        <>Profit after ad spend can&apos;t be worked out yet.</>
      )}
    </p>
  );
}

function Notes({ orgId, notes }: { orgId: string; notes: Map<string, Note> }) {
  if (notes.size === 0) return null;
  return (
    <section aria-labelledby="overview-notes" className={own.notes}>
      <h3 id="overview-notes" className={own.notesTitle}>
        Why some figures are missing
      </h3>
      <ol className={own.noteList}>
        {[...notes.values()].map((note) => {
          const fix = FIXES[note.key];
          return (
            <li key={note.key} id={`overview-note-${note.number}`}>
              {note.text}.
              {fix ? (
                <>
                  {" "}
                  <Link href={`/orgs/${orgId}${fix.path}`}>{fix.label}</Link>
                </>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** The period's figures as a ledger: one row per figure, amounts aligned, trends beside them. */
function Ledger({
  data,
  currency,
  notes,
}: {
  data: Overview;
  currency: ReportingCurrency;
  notes: Map<string, Note>;
}) {
  const define = definitionsByKey(data.definitions);
  return (
    <div className={own.ledger}>
      {OVERVIEW_GROUPS.map((group) => (
        <section key={group.id} aria-labelledby={`overview-${group.id}`}>
          <h3 id={`overview-${group.id}`}>{group.title}</h3>
          <table className={own.ledgerTable} aria-labelledby={`overview-${group.id}`}>
            <thead className="visually-hidden">
              <tr>
                <th scope="col">Figure</th>
                <th scope="col">This period</th>
                <th scope="col">By day</th>
              </tr>
            </thead>
            <tbody>
              {group.keys.map((key) => {
                const d = define(key);
                const figure = data.totals[key] as Figure | undefined;
                const missing = missingOf(figure);
                const note = missing ? noteOf(notes, figure) : undefined;
                return (
                  <tr key={key}>
                    <th scope="row">
                      <span className={own.figureName}>{d.label}</span>
                      {d.note ? <span className={own.figureNote}>{d.note}</span> : null}
                      <HowCalculated definition={d} withNote={false} />
                    </th>
                    <td className={own.amount}>
                      {missing ? (
                        <span className={own.missing}>
                          {formatFigure(figure, d.unit, currency)}
                          {note ? (
                            <a
                              href={`#overview-note-${note.number}`}
                              className={own.noteRef}
                              aria-label={`Note ${note.number}`}
                            >
                              {note.number}
                            </a>
                          ) : null}
                        </span>
                      ) : (
                        <span data-figure>{formatFigure(figure, d.unit, currency)}</span>
                      )}
                    </td>
                    <td className={own.trend}>
                      {TREND_KEYS.has(key) && !missing ? (
                        <Sparkline values={trend(data, key)} />
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ))}
    </div>
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
  const notes = notesFor(data);

  return (
    <>
      <section aria-labelledby="overview-figures" className={styles.section}>
        <h2 id="overview-figures" className="visually-hidden">
          Sales, ad spend and profit
        </h2>
        {controls.toolbar}
        <Statement org={org} data={data} currency={currency} />
        <PeriodLine data={data}>
          Your stores&apos; sales, what Google Ads and Meta report as spent, and Google
          Analytics&apos; visits, put together by AdVegaX.
        </PeriodLine>
        <Notes orgId={org.id} notes={notes} />
        <Ledger data={data} currency={currency} notes={notes} />
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
