"use client";

import Link from "next/link";
import { useId, useMemo, useState, type KeyboardEvent, type PointerEvent } from "react";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { entityStatus, providerName } from "@/features/advertising/labels";
import { useFunnel } from "@/features/funnel/api";
import type { Organization } from "@/features/organizations/api";
import { formatDay } from "@/features/stores/dates";
import type { Figure } from "@/lib/format/money";
import { numberFormat } from "@/lib/format/number-format";

import { useCampaigns, useChannels, type Overview } from "./api";
import dash from "./dashboard.module.css";
import { definitionsByKey, formatFigure, type ReportingCurrency } from "./labels";

/**
 * The Overview's high-level dashboard (Phase 19): the period by day, where the money went, the
 * funnel at a glance and the campaigns that spent most. Every number is the API's own figure,
 * formatted the same way as the tables below; a missing figure says why, never 0.
 */

type Controls = { from: string; to: string; storeId: string | null };

const valueOf = (figure: Figure | undefined): number | null =>
  figure && figure.availability === "available" && figure.value !== null
    ? Number(figure.value)
    : null;

/** The next "round" number at or above ``value`` (1, 2, 2.5 or 5 × a power of ten), so the
 * axis reads A$1K / A$500 / A$0 rather than A$1K / A$500.3. Drawing only, not a figure. */
function niceCeiling(value: number): number {
  if (value <= 0) return 0;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * power >= value) ?? 10;
  return step * power;
}

function compactMoney(value: number, currency: ReportingCurrency): string {
  return numberFormat(undefined, {
    style: "currency",
    currency: currency.currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** A horizontal bar drawn in SVG (the app's security policy allows no inline styles). */
function Meter({ share, className }: { share: number; className: string }) {
  return (
    <svg
      className={dash.meter}
      viewBox="0 0 100 8"
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <rect className={dash.meterTrack} x={0} y={0} width={100} height={8} rx={4} />
      <rect
        className={`${dash.meterFill} ${className}`}
        x={0}
        y={0}
        width={Math.max(0, Math.min(1, share)) * 100}
        height={8}
        rx={4}
      />
    </svg>
  );
}

// ------------------------------------------------------------------ the period by day
const SERIES = [
  { key: "net_sales", label: "Net sales", mark: "line", className: dash.lineSales },
  {
    key: "profit_after_ad_spend",
    label: "Profit after ad spend",
    mark: "line",
    className: dash.lineProfit,
  },
  { key: "ad_spend", label: "Ad spend", mark: "bar", className: dash.barSpend },
] as const;

const W = 1000;
const H = 300;

export function TrendChart({ data, currency }: { data: Overview; currency: ReportingCurrency }) {
  const define = definitionsByKey(data.definitions);
  const titleId = useId();
  const days = data.days;
  const values = useMemo(
    () => SERIES.map((s) => days.map((d) => valueOf(d.figures[s.key] as Figure | undefined))),
    [days],
  );
  const [active, setActive] = useState<number | null>(null);
  const present = values.flat().filter((v): v is number => v !== null);
  if (days.length < 2 || present.length === 0) {
    return (
      <section aria-labelledby={titleId} className={dash.card}>
        <h2 id={titleId} className={dash.cardTitle}>
          Sales, ad spend and profit by day
        </h2>
        <p className={dash.cardLead}>
          No daily figures for this period yet. They appear here once a store or ad account has been
          read.
        </p>
      </section>
    );
  }
  const top = niceCeiling(Math.max(...present, 0));
  const bottom = 0 - niceCeiling(-Math.min(...present, 0)); // never "-A$0"
  const span = top - bottom || 1;
  const y = (v: number) => H - ((v - bottom) / span) * H;
  const step = W / days.length;
  const x = (i: number) => step * i + step / 2;
  const zero = y(0);
  const lines = SERIES.map((s, n) => {
    if (s.mark !== "line") return null;
    const runs: string[] = [];
    let run: string[] = [];
    values[n]!.forEach((v, i) => {
      if (v === null) {
        if (run.length) runs.push(run.join(" "));
        run = [];
      } else run.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    });
    if (run.length) runs.push(run.join(" "));
    return runs;
  });
  const spendIndex = SERIES.findIndex((s) => s.key === "ad_spend");
  const ticks = [top, bottom + span * 0.5, bottom];
  const shown = active ?? days.length - 1;
  const pick = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const i = Math.floor(((event.clientX - box.left) / box.width) * days.length);
    setActive(Math.max(0, Math.min(days.length - 1, i)));
  };
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };
    if (event.key === "Home") setActive(0);
    else if (event.key === "End") setActive(days.length - 1);
    else if (event.key in moves)
      setActive(Math.max(0, Math.min(days.length - 1, shown + moves[event.key]!)));
    else return;
    event.preventDefault();
  };
  const day = days[shown]!;
  return (
    <section aria-labelledby={titleId} className={dash.card}>
      <div className={dash.cardHead}>
        <h2 id={titleId} className={dash.cardTitle}>
          Sales, ad spend and profit by day
        </h2>
        <ul className={dash.legend} aria-label="Key">
          {SERIES.map((s) => (
            <li key={s.key}>
              <span
                className={`${dash.swatch} ${s.mark === "bar" ? dash.swatchBar : ""} ${s.className}`}
                aria-hidden="true"
              />
              {define(s.key).label}
            </li>
          ))}
        </ul>
      </div>
      <div className={dash.readout} aria-live="polite">
        <p className={dash.readoutDay}>{formatDay(day.day)}</p>
        <dl>
          {SERIES.map((s) => (
            <div key={s.key}>
              <dt>
                <span
                  className={`${dash.swatch} ${s.mark === "bar" ? dash.swatchBar : ""} ${s.className}`}
                  aria-hidden="true"
                />
                {define(s.key).label}
              </dt>
              <dd data-figure>
                {formatFigure(day.figures[s.key] as Figure | undefined, "money", currency)}
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className={dash.chartFrame}>
        <ol className={dash.yAxis} aria-hidden="true">
          {ticks.map((t) => (
            <li key={t}>{compactMoney(t, currency)}</li>
          ))}
        </ol>
        <div
          className={dash.chart}
          role="group"
          tabIndex={0}
          aria-label="Chart by day. Use the left and right arrow keys to read each day; the same figures are in the table under All figures."
          onPointerMove={pick}
          onPointerDown={pick}
          onPointerLeave={() => setActive(null)}
          onKeyDown={keys}
        >
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="none"
            aria-hidden="true"
            focusable="false"
          >
            {[0.25, 0.5, 0.75].map((f) => (
              <line key={f} x1={0} x2={W} y1={H * f} y2={H * f} className={dash.grid} />
            ))}
            <line x1={0} x2={W} y1={zero} y2={zero} className={dash.baseline} />
            {values[spendIndex]!.map((v, i) =>
              v === null ? null : (
                <rect
                  key={days[i]!.day}
                  x={x(i) - step * 0.3}
                  width={step * 0.6}
                  y={Math.min(y(v), zero)}
                  height={Math.max(1, Math.abs(zero - y(v)))}
                  className={`${dash.bar} ${SERIES[spendIndex]!.className}`}
                />
              ),
            )}
            {lines.map((runs, n) =>
              runs?.map((points) => (
                <polyline
                  key={`${SERIES[n]!.key}-${points.slice(0, 12)}`}
                  points={points}
                  pathLength={1}
                  className={`${dash.line} ${SERIES[n]!.className}`}
                  vectorEffect="non-scaling-stroke"
                />
              )),
            )}
            <line x1={x(shown)} x2={x(shown)} y1={0} y2={H} className={dash.cursor} />
          </svg>
        </div>
      </div>
      <p className={dash.xAxis} aria-hidden="true">
        <span>{formatDay(days[0]!.day)}</span>
        <span>{formatDay(days[Math.floor(days.length / 2)]!.day)}</span>
        <span>{formatDay(days[days.length - 1]!.day)}</span>
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ where the money went

export function MoneyBreakdown({ org, controls }: { org: Organization; controls: Controls }) {
  const titleId = useId();
  const channels = useChannels(org.id, controls.from, controls.to, controls.storeId);
  const data = channels.data;
  if (!data)
    return (
      <section className={dash.card} aria-busy="true" aria-labelledby={titleId}>
        <h2 id={titleId} className={dash.cardTitle}>
          Where the money went
        </h2>
        <p className={dash.cardLead}>Loading…</p>
      </section>
    );
  const define = definitionsByKey(data.definitions);
  const currency = { currency: data.reporting_currency, minorUnits: data.currency_minor_units };
  const platforms = data.platforms
    .map((p) => ({
      name: providerName(p.provider),
      spend: p.figures.spend as Figure | undefined,
      value: p.figures.conversion_value as Figure | undefined,
      roas: p.figures.platform_roas as Figure | undefined,
    }))
    .sort((a, b) => (valueOf(b.spend) ?? -1) - (valueOf(a.spend) ?? -1));
  // Bar lengths are drawing, not figures: each platform's spend against the largest one.
  const largestSpend = Math.max(0, ...platforms.map((p) => valueOf(p.spend) ?? 0));
  const visits = data.analytics_channels
    .map((c) => {
      const figure = c.figures.sessions as Figure | undefined;
      return { name: c.channel, figure, sessions: valueOf(figure) ?? 0 };
    })
    .filter((c) => c.sessions > 0)
    .sort((a, b) => b.sessions - a.sessions);
  const largestVisits = Math.max(0, ...visits.map((c) => c.sessions));
  return (
    <section aria-labelledby={titleId} className={dash.card}>
      <h2 id={titleId} className={dash.cardTitle}>
        Where the money went
      </h2>
      <h3 className={dash.subTitle}>
        Ad spend by platform:{" "}
        <span data-figure>{formatFigure(data.ad_spend, "money", currency)}</span>
      </h3>
      {platforms.length === 0 ? (
        <p className={dash.cardLead}>
          No ad account is connected. <Link href={`/orgs/${org.id}/connections`}>Connect one</Link>
        </p>
      ) : (
        <ul className={dash.bars} aria-label="Ad spend by platform">
          {platforms.map((p) => {
            const spend = valueOf(p.spend);
            const length = spend !== null && largestSpend > 0 ? spend / largestSpend : 0;
            return (
              <li key={p.name} className={dash.barRow}>
                <span className={dash.barName}>{p.name}</span>
                <span className={dash.barValue} data-figure>
                  {formatFigure(p.spend, define("spend").unit, currency)}
                </span>
                <Meter share={length} className={dash.fillTwo!} />
                <span className={dash.barNote}>
                  {define("conversion_value").label}:{" "}
                  {formatFigure(p.value, define("conversion_value").unit, currency)}
                  {" · "}
                  {define("platform_roas").label}:{" "}
                  {formatFigure(p.roas, define("platform_roas").unit, currency)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <h3 className={dash.subTitle}>Visits by channel (Google Analytics)</h3>
      {visits.length === 0 ? (
        <p className={dash.cardLead}>
          {data.analytics_channels_missing
            ? formatFigure(data.analytics_channels_missing, "count", currency)
            : "No visits in this period."}
        </p>
      ) : (
        <ul className={dash.bars} aria-label="Visits by channel">
          {visits.map((c) => (
            <li key={c.name} className={dash.barRow}>
              <span className={dash.barName}>{c.name}</span>
              <span className={dash.barValue} data-figure>
                {formatFigure(c.figure, "count", currency)}
              </span>
              <Meter share={c.sessions / largestVisits} className={dash.fillOne!} />
            </li>
          ))}
        </ul>
      )}
      <p className={dash.cardFoot}>
        <Link href={`/orgs/${org.id}/reports`}>Channels and campaigns in detail</Link>
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ the funnel at a glance
export function FunnelSnapshot({ org, controls }: { org: Organization; controls: Controls }) {
  const titleId = useId();
  const funnel = useFunnel(org.id, controls.from, controls.to, controls.storeId);
  const data = funnel.data;
  if (!data)
    return (
      <section className={dash.card} aria-busy="true" aria-labelledby={titleId}>
        <h2 id={titleId} className={dash.cardTitle}>
          From first view to purchase
        </h2>
        <p className={dash.cardLead}>Loading…</p>
      </section>
    );
  const define = definitionsByKey(data.definitions);
  const currency = { currency: data.reporting_currency, minorUnits: data.currency_minor_units };
  const order: string[] = [];
  for (const s of data.steps) {
    if (!order.includes(s.from_stage)) order.push(s.from_stage);
    if (!order.includes(s.to_stage)) order.push(s.to_stage);
  }
  const stages = order.filter((k) => k in data.stages && k !== "analytics_purchases");
  const counts = stages.map((k) => valueOf(data.stages[k]));
  // Each step's rate is the API's (its definition decides what can be compared).
  const rateInto = new Map(data.steps.map((st) => [st.to_stage, st.rate ?? undefined]));
  const rates = stages.map((k, i) => (i === 0 ? null : valueOf(rateInto.get(k))));
  // Flagged: steps the API found well below their usual rate (a low click rate alone is normal).
  const below = new Set(data.findings.filter((f) => f.view === "whole").map((f) => f.to_stage));
  const first = counts[0] ?? null;
  return (
    <section aria-labelledby={titleId} className={dash.card}>
      <h2 id={titleId} className={dash.cardTitle}>
        From first view to purchase
      </h2>
      <ol className={dash.funnel}>
        {stages.map((key, i) => {
          const count = counts[i] ?? null;
          // Square-root scale: impressions and purchases differ a thousandfold, and a linear
          // bar would hide every step after the first.
          const width = count !== null && first ? Math.max(0.02, Math.sqrt(count / first)) : 0;
          return (
            <li key={key} className={dash.funnelRow} data-weakest={below.has(key) || undefined}>
              <span className={dash.funnelName}>{define(key).label}</span>
              <span className={dash.funnelValue} data-figure>
                {formatFigure(data.stages[key], "count", currency)}
              </span>
              <Meter share={width} className={below.has(key) ? dash.fillWeak! : dash.fillOne!} />
              {rates[i] !== null ? (
                <span className={dash.funnelRate}>
                  {formatFigure(rateInto.get(key), "ratio", currency)} of the step before
                  {below.has(key) ? (
                    <>
                      {" "}
                      <Badge tone="warning">Below usual</Badge>
                    </>
                  ) : null}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      <p className={dash.cardFoot}>
        {data.findings.length
          ? `${data.findings.length} ${data.findings.length === 1 ? "step is" : "steps are"} well below usual. `
          : ""}
        <Link href={`/orgs/${org.id}/funnel`}>Open the funnel</Link>
      </p>
    </section>
  );
}

// ------------------------------------------------------------------ campaigns that spent most
const TONE: Record<string, BadgeTone> = { ok: "success", off: "neutral", warn: "warning" };

export function TopCampaigns({ org, controls }: { org: Organization; controls: Controls }) {
  const titleId = useId();
  const campaigns = useCampaigns(org.id, controls.from, controls.to, controls.storeId);
  const data = campaigns.data;
  if (!data) return null;
  const define = definitionsByKey(data.definitions);
  const currency = { currency: data.reporting_currency, minorUnits: data.currency_minor_units };
  const top = [...data.items]
    .filter((c) => (valueOf(c.figures.spend as Figure | undefined) ?? 0) > 0)
    .sort(
      (a, b) =>
        (valueOf(b.figures.spend as Figure | undefined) ?? 0) -
        (valueOf(a.figures.spend as Figure | undefined) ?? 0),
    )
    .slice(0, 5);
  const fig = (c: (typeof top)[number], key: string) =>
    formatFigure(c.figures[key] as Figure | undefined, define(key).unit, currency);
  return (
    <section aria-labelledby={titleId} className={`${dash.card} ${dash.wide}`}>
      <div className={dash.cardHead}>
        <h2 id={titleId} className={dash.cardTitle}>
          Campaigns that spent most
        </h2>
        <Link href={`/orgs/${org.id}/advertising`} className={dash.headLink}>
          All campaigns
        </Link>
      </div>
      {top.length === 0 ? (
        <p className={dash.cardLead}>No campaign spent anything in this period.</p>
      ) : (
        <table className={dash.campaigns} aria-labelledby={titleId}>
          <thead>
            <tr>
              <th scope="col">Campaign</th>
              <th scope="col" className={dash.num}>
                {define("spend").label}
              </th>
              <th scope="col" className={dash.num}>
                {define("conversion_value").label}
              </th>
              <th scope="col" className={dash.num}>
                {define("platform_roas").label}
              </th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {top.map((c) => {
              const status = entityStatus(c.status);
              return (
                <tr key={c.id}>
                  <th scope="row">
                    <Link href={`/orgs/${org.id}/advertising/campaigns/${c.id}`}>{c.name}</Link>
                    <span className={dash.campaignMeta}>{providerName(c.provider)}</span>
                  </th>
                  <td className={dash.num} data-label={define("spend").label} data-figure>
                    {fig(c, "spend")}
                  </td>
                  <td
                    className={dash.num}
                    data-label={define("conversion_value").label}
                    data-figure
                  >
                    {fig(c, "conversion_value")}
                  </td>
                  <td className={dash.num} data-label={define("platform_roas").label} data-figure>
                    {fig(c, "platform_roas")}
                  </td>
                  <td data-label="Status">
                    <Badge tone={TONE[status.tone] ?? "neutral"}>{status.label}</Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** The dashboard grid, between the key figures and the work waiting for the reader. */
export function Dashboard({
  org,
  data,
  currency,
  controls,
}: {
  org: Organization;
  data: Overview;
  currency: ReportingCurrency;
  controls: Controls;
}) {
  return (
    <div className={dash.board}>
      <div className={dash.wide}>
        <TrendChart data={data} currency={currency} />
      </div>
      <MoneyBreakdown org={org} controls={controls} />
      <FunnelSnapshot org={org} controls={controls} />
      <TopCampaigns org={org} controls={controls} />
    </div>
  );
}
