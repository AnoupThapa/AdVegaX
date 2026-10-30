"use client";

import { useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { entityStatus, providerName } from "@/features/advertising/labels";
import type { MetricDefinition } from "@/features/overview/api";
import { definitionsByKey, formatFigure } from "@/features/overview/labels";
import {
  FigureCell,
  HowCalculated,
  PeriodLine,
  ScrollTable,
  Sources,
  reportingCurrency,
  useReportControls,
  type Context,
} from "@/features/overview/Shared";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import type { Organization } from "@/features/organizations/api";
import { messageFor } from "@/lib/api/errors";
import { figureReason, formatFigureRatio, type Figure } from "@/lib/format/money";

import {
  useCampaignFunnels,
  useFunnel,
  useLandingPageFunnels,
  type CampaignFunnels,
  type Funnel,
  type FunnelStep,
  type LandingPages,
} from "./api";
import own from "./funnel.module.css";
import {
  DIFFERENT_SOURCES,
  FUNNEL_VIEWS,
  findingText,
  stageSource,
  stepLabel,
  type FunnelView,
} from "./labels";

type Stages = Record<string, Figure>;
const asStages = (stages: Record<string, unknown> | null | undefined) =>
  (stages ?? {}) as unknown as Stages;

/** The largest count of a funnel, so each bar is drawn against it (no figure is changed). */
function largest(stages: Stages): number {
  return Math.max(1, ...Object.values(stages).map((f) => (f.value === null ? 0 : Number(f.value))));
}

/** The stages as bars with their counts and sources, and "How is this calculated?". */
function StageBars({
  stages,
  definitions,
  provider,
  label,
}: {
  stages: Stages;
  definitions: readonly MetricDefinition[];
  provider?: string;
  label: string;
}) {
  const define = definitionsByKey(definitions);
  const top = largest(stages);
  const none = { currency: "AUD", minorUnits: 2 };
  return (
    <ol className={own.stages} aria-label={label}>
      {Object.entries(stages).map(([key, figure]) => {
        const d = define(key);
        const text = formatFigure(figure, "count", none);
        return (
          <li key={key} className={own.stage}>
            <p className={own.stageLine}>
              <span className={own.stageLabel}>{d.label}</span>{" "}
              <span className={figure.availability === "available" ? own.count : styles.missing}>
                {text}
              </span>
            </p>
            {figure.availability === "available" && figure.value !== null ? (
              <meter
                className={own.bar}
                min={0}
                max={top}
                value={Number(figure.value)}
                aria-label={`${d.label}: ${text}`}
              />
            ) : null}
            <p className={styles.muted}>{stageSource(d, provider)}</p>
            <HowCalculated definition={d} />
          </li>
        );
      })}
    </ol>
  );
}

function StepList({
  steps,
  definitions,
  label,
}: {
  steps: readonly FunnelStep[];
  definitions: readonly MetricDefinition[];
  label: string;
}) {
  return (
    <ul className={own.steps} aria-label={label}>
      {steps.map((step) => (
        <li key={`${step.from_stage}-${step.to_stage}`}>
          <span>{stepLabel(step, definitions)}: </span>
          {step.rate === null || step.rate === undefined ? (
            <span className={styles.muted}>{DIFFERENT_SOURCES}</span>
          ) : (
            <strong>{formatFigureRatio(step.rate as Figure)}</strong>
          )}
        </li>
      ))}
    </ul>
  );
}

function Findings({ data }: { data: Funnel }) {
  return (
    <section aria-labelledby="funnel-findings" className={styles.section}>
      <h2 id="funnel-findings">Where buyers drop out</h2>
      {data.findings.length === 0 ? (
        <p className={styles.muted}>
          No step fell clearly below its usual level in this period. A step is flagged when it is at
          least {formatFigureRatio({ value: data.rules.drop_share, availability: "available" })}{" "}
          lower than in the previous period of the same length and below its own{" "}
          {data.rules.baseline_days}-day average, with at least {data.rules.min_events} events
          before it.
        </p>
      ) : (
        <ul className={own.findings}>
          {data.findings.map((f) => (
            <li key={`${f.view}-${f.subject ?? ""}-${f.from_stage}-${f.to_stage}`}>
              {findingText(
                f,
                f.view === "platform" ? data.platform_definitions : data.definitions,
                data.rules.previous_from,
                data.rules.previous_to,
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function WholeView({ data }: { data: Funnel }) {
  return (
    <section aria-labelledby="funnel-whole" className={styles.section}>
      <h2 id="funnel-whole">From impression to purchase</h2>
      <PeriodLine data={data}>
        Events, not people: one shopper can view several products. Each stage says where its number
        comes from.
      </PeriodLine>
      <StageBars stages={asStages(data.stages)} definitions={data.definitions} label="Stages" />
      <h3>Steps</h3>
      <StepList steps={data.steps} definitions={data.definitions} label="Steps" />
    </section>
  );
}

function PlatformsView({ data }: { data: Funnel }) {
  if (data.platforms.length === 0)
    return <p className={styles.muted}>{figureReason(data.stages.impressions as Figure)}.</p>;
  return (
    <>
      {data.platforms.map((p) => (
        <section
          key={p.provider}
          aria-labelledby={`funnel-${p.provider}`}
          className={styles.section}
        >
          <h2 id={`funnel-${p.provider}`}>{providerName(p.provider)}</h2>
          <p className={styles.source}>
            Reported by {providerName(p.provider)} for{" "}
            {p.ad_accounts === 1 ? "1 ad account" : `${p.ad_accounts} ad accounts`}, with its own
            attribution. Never added to another platform&apos;s figures.
          </p>
          <StageBars
            stages={asStages(p.stages)}
            definitions={data.platform_definitions}
            provider={p.provider}
            label={`${providerName(p.provider)} stages`}
          />
          <StepList
            steps={p.steps}
            definitions={data.platform_definitions}
            label={`${providerName(p.provider)} steps`}
          />
        </section>
      ))}
    </>
  );
}

/** Rows of funnels as a table: each stage's count, then each step's rate. */
function FunnelTable({
  label,
  caption,
  first,
  rows,
  definitions,
  context,
}: {
  label: string;
  caption: string;
  first: string;
  rows: Array<{ key: string; name: ReactNode; stages: Stages; steps: readonly FunnelStep[] }>;
  definitions: readonly MetricDefinition[];
  context: Context;
}) {
  const define = definitionsByKey(definitions);
  const sample = rows[0];
  if (!sample) return null;
  const keys = Object.keys(sample.stages);
  const currency = reportingCurrency(context);
  return (
    <ScrollTable label={label}>
      <table className={styles.table}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{first}</th>
            {keys.map((k) => (
              <th key={k} scope="col" className={styles.num}>
                {define(k).label}
              </th>
            ))}
            {sample.steps.map((s) => (
              <th key={`${s.from_stage}-${s.to_stage}`} scope="col" className={styles.num}>
                {stepLabel(s, definitions)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.name}</th>
              {keys.map((k) => (
                <FigureCell key={k} figure={row.stages[k]} unit="count" currency={currency} />
              ))}
              {row.steps.map((s) => (
                <FigureCell
                  key={`${s.from_stage}-${s.to_stage}`}
                  figure={s.rate as Figure | null}
                  unit="ratio"
                  currency={currency}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  );
}

function ChannelsView({ data }: { data: Funnel }) {
  return (
    <section aria-labelledby="funnel-channels" className={styles.section}>
      <h2 id="funnel-channels">Google Analytics channels</h2>
      <p className={styles.source}>Reported by Google Analytics, most visits first.</p>
      {data.channels.length === 0 ? (
        <p className={styles.muted}>
          {data.channels_missing
            ? `${figureReason(data.channels_missing as Figure)}.`
            : "No visits in this period."}
        </p>
      ) : (
        <FunnelTable
          label="Channel funnels"
          caption="Each channel's own funnel: events, then the share that went on to the next stage."
          first="Channel"
          rows={data.channels.map((c) => ({
            key: c.channel,
            name: c.channel,
            stages: asStages(c.stages),
            steps: c.steps,
          }))}
          definitions={data.definitions}
          context={data}
        />
      )}
    </section>
  );
}

const CAMPAIGN_PLATFORM = ["impressions", "clicks", "purchases"] as const;
const CAMPAIGN_ANALYTICS = ["landing_page_views", "adds_to_cart", "analytics_purchases"] as const;

function CampaignsView({ data }: { data: CampaignFunnels }) {
  const define = definitionsByKey(data.definitions);
  const platform = definitionsByKey(data.platform_definitions);
  const currency = reportingCurrency(data);
  const accounts = new Map(
    data.sources.filter((s) => s.kind === "ad_account").map((s) => [s.id, s.name]),
  );
  const gaCells = (stages: Stages | null, why: Figure | null | undefined) =>
    stages ? (
      CAMPAIGN_ANALYTICS.map((k) => (
        <FigureCell key={k} figure={stages[k]} unit="count" currency={currency} />
      ))
    ) : (
      <td colSpan={CAMPAIGN_ANALYTICS.length} className={styles.missing}>
        {why ? figureReason(why) : ""}
      </td>
    );
  return (
    <section aria-labelledby="funnel-campaigns" className={styles.section}>
      <h2 id="funnel-campaigns">Campaigns</h2>
      <PeriodLine data={data}>
        Each campaign as its platform reports it, and Google Analytics&apos; funnel for the campaign
        with exactly the same name. Visits from no campaign are &quot;Other traffic&quot;, so the
        campaigns and other traffic add up to the website.
      </PeriodLine>
      {data.items.length === 0 ? (
        <p className={styles.muted}>No campaigns for this choice.</p>
      ) : (
        <ScrollTable label="Campaign funnels">
          <table className={styles.table}>
            <caption>
              The first three columns are the platform&apos;s own; the last three are Google
              Analytics&apos; for the campaign of the same name.
            </caption>
            <thead>
              <tr>
                <th scope="col">Campaign</th>
                {CAMPAIGN_PLATFORM.map((k) => (
                  <th key={k} scope="col" className={styles.num}>
                    {platform(k).label}
                  </th>
                ))}
                {CAMPAIGN_ANALYTICS.map((k) => (
                  <th key={k} scope="col" className={styles.num}>
                    {define(k).label} (Google Analytics)
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => (
                <tr key={c.id}>
                  <th scope="row">
                    {c.name}
                    <span className={styles.unsettled}>
                      {[
                        providerName(c.provider),
                        accounts.get(c.ad_account_id),
                        entityStatus(c.status).label,
                        c.shared_match ? "shares its Google Analytics match" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </th>
                  {CAMPAIGN_PLATFORM.map((k) => (
                    <FigureCell
                      key={k}
                      figure={asStages(c.stages)[k]}
                      unit="count"
                      currency={currency}
                    />
                  ))}
                  {gaCells(
                    c.analytics ? asStages(c.analytics) : null,
                    data.analytics_missing as Figure | null,
                  )}
                </tr>
              ))}
              {data.other_traffic ? (
                <tr>
                  <th scope="row">Other traffic</th>
                  <td colSpan={CAMPAIGN_PLATFORM.length} className={styles.muted}>
                    Visits from no campaign
                  </td>
                  {gaCells(asStages(data.other_traffic), null)}
                </tr>
              ) : null}
              {data.website ? (
                <tr>
                  <th scope="row">Website</th>
                  <td colSpan={CAMPAIGN_PLATFORM.length} className={styles.muted}>
                    Campaigns and other traffic
                  </td>
                  {gaCells(asStages(data.website), null)}
                </tr>
              ) : null}
            </tbody>
          </table>
        </ScrollTable>
      )}
    </section>
  );
}

function LandingPagesView({ data }: { data: LandingPages }) {
  return (
    <section aria-labelledby="funnel-pages" className={styles.section}>
      <h2 id="funnel-pages">Landing pages</h2>
      <PeriodLine data={data}>
        The page each visit started on (without anything after a “?”), most visits first.
      </PeriodLine>
      {data.items.length === 0 ? (
        <p className={styles.muted}>
          {data.items_missing
            ? `${figureReason(data.items_missing as Figure)}.`
            : "No visits in this period."}
        </p>
      ) : (
        <FunnelTable
          label="Landing page funnels"
          caption={
            data.item_count > data.items.length
              ? `Showing the ${data.items.length} pages with the most visits of ${data.item_count}.`
              : "Each landing page's own funnel, reported by Google Analytics."
          }
          first="Landing page"
          rows={data.items.map((p) => ({
            key: p.landing_page,
            name: <span className={own.path}>{p.landing_page}</span>,
            stages: asStages(p.stages),
            steps: p.steps,
          }))}
          definitions={data.definitions}
          context={data}
        />
      )}
    </section>
  );
}

function Loaded<T extends Context>({
  query,
  render,
}: {
  query: { error: unknown; data: T | undefined };
  render: (data: T) => ReactNode;
}) {
  if (query.error) return <Alert tone="error">{messageFor(query.error)}</Alert>;
  if (!query.data) return <p role="status">Loading the funnel…</p>;
  return (
    <>
      {render(query.data)}
      <Sources data={query.data} />
    </>
  );
}

type Args = { orgId: string; from: string; to: string; storeId: string | null };

function WholeData({ view, ...a }: Args & { view: FunnelView }) {
  const query = useFunnel(a.orgId, a.from, a.to, a.storeId);
  return (
    <Loaded
      query={query}
      render={(d) => (
        <>
          <Findings data={d} />
          {view === "whole" ? <WholeView data={d} /> : null}
          {view === "platforms" ? <PlatformsView data={d} /> : null}
          {view === "channels" ? <ChannelsView data={d} /> : null}
        </>
      )}
    />
  );
}

function CampaignData(a: Args) {
  const query = useCampaignFunnels(a.orgId, a.from, a.to, a.storeId);
  return <Loaded query={query} render={(d) => <CampaignsView data={d} />} />;
}

function LandingPageData(a: Args) {
  const query = useLandingPageFunnels(a.orgId, a.from, a.to, a.storeId);
  return <Loaded query={query} render={(d) => <LandingPagesView data={d} />} />;
}

function Body({ org, view }: { org: Organization; view: FunnelView }) {
  const controls = useReportControls(org);
  const args: Args = {
    orgId: org.id,
    from: controls.from,
    to: controls.to,
    storeId: controls.storeId,
  };
  return (
    <>
      {controls.toolbar}
      {view === "campaigns" ? <CampaignData {...args} /> : null}
      {view === "landing-pages" ? <LandingPageData {...args} /> : null}
      {view !== "campaigns" && view !== "landing-pages" ? (
        <WholeData {...args} view={view} />
      ) : null}
    </>
  );
}

/** The funnel from impression to purchase (PLAN §9, task 7-07). */
export function FunnelPage() {
  const org = useCurrentOrganization();
  const [view, setView] = useState<FunnelView>("whole");
  return (
    <section aria-labelledby="funnel-title">
      <PageHeading id="funnel-title">Funnel</PageHeading>
      <p className={styles.source}>
        From the first ad impression to the purchase: where buyers drop out.
      </p>
      <SelectField
        label="Show"
        options={FUNNEL_VIEWS}
        value={view}
        onChange={(event) => setView(event.target.value as FunnelView)}
      />
      <Body org={org} view={view} />
    </section>
  );
}
