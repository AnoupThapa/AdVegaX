"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { entityStatus, providerName } from "@/features/advertising/labels";
import type { Organization } from "@/features/organizations/api";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { messageFor } from "@/lib/api/errors";
import { figureReason, type Figure } from "@/lib/format/money";

import {
  useCampaigns,
  useChannels,
  useProductFigures,
  type Campaigns,
  type Channels,
  type Products,
  type Report,
} from "./api";
import { definitionsByKey, formatFigure } from "./labels";
import {
  ColumnDefinitions,
  FigureCell,
  PeriodLine,
  ScrollTable,
  Sources,
  reportingCurrency,
  useReportControls,
  type Context,
} from "./Shared";

const REPORTS = [
  { value: "channels", label: "Channels" },
  { value: "campaigns", label: "Campaigns" },
  { value: "products", label: "Products" },
] as const;

const PLATFORM_COLUMNS = [
  "spend",
  "clicks",
  "impressions",
  "conversions",
  "conversion_value",
  "platform_roas",
  "cost_per_click",
  "cost_per_conversion",
] as const;
const CHANNEL_COLUMNS = [
  "sessions",
  "engaged_sessions",
  "engagement_rate",
  "key_events",
  "purchases",
  "purchase_revenue",
] as const;
const CAMPAIGN_COLUMNS = [
  "spend",
  "clicks",
  "conversions",
  "conversion_value",
  "platform_roas",
  "cost_per_conversion",
  "budget_use",
] as const;
const CAMPAIGN_ANALYTICS = ["sessions", "purchases", "purchase_revenue"] as const;
const PRODUCT_COLUMNS = [
  "units",
  "net_sales",
  "product_cost",
  "gross_profit",
  "gross_margin",
] as const;

const fig = (figures: Record<string, unknown> | null | undefined, key: string) =>
  (figures?.[key] ?? undefined) as Figure | undefined;

function HeaderCells({ context, keys }: { context: Context; keys: readonly string[] }) {
  const define = definitionsByKey(context.definitions);
  return (
    <>
      {keys.map((key) => (
        <th key={key} scope="col" className={styles.num}>
          {define(key).label}
        </th>
      ))}
    </>
  );
}

function FigureCells({
  context,
  keys,
  figures,
}: {
  context: Context;
  keys: readonly string[];
  figures: Record<string, unknown> | null | undefined;
}) {
  const define = definitionsByKey(context.definitions);
  const currency = reportingCurrency(context);
  return (
    <>
      {keys.map((key) => (
        <FigureCell
          key={key}
          figure={fig(figures, key)}
          unit={define(key).unit}
          currency={currency}
        />
      ))}
    </>
  );
}

function ChannelsReport({ data }: { data: Channels }) {
  const currency = reportingCurrency(data);
  return (
    <>
      <section aria-labelledby="report-platforms" className={styles.section}>
        <h2 id="report-platforms">Ad platforms</h2>
        <PeriodLine data={data}>
          Each platform&apos;s own reported figures. Conversions and their value are counted by each
          platform with its own attribution, so they are never added across platforms.
        </PeriodLine>
        <p>
          Ad spend, all platforms together:{" "}
          <strong>{formatFigure(data.ad_spend as Figure, "money", currency)}</strong>
        </p>
        {data.platforms.length === 0 ? (
          <p className={styles.muted}>{figureReason(data.ad_spend as Figure)}.</p>
        ) : (
          <ScrollTable label="Ad platforms">
            <table className={styles.table}>
              <caption>Reported by each platform, in {data.reporting_currency}.</caption>
              <thead>
                <tr>
                  <th scope="col">Platform</th>
                  <HeaderCells context={data} keys={PLATFORM_COLUMNS} />
                </tr>
              </thead>
              <tbody>
                {data.platforms.map((p) => (
                  <tr key={p.provider}>
                    <th scope="row">
                      {providerName(p.provider)}
                      <span className={styles.unsettled}>
                        {p.ad_accounts === 1 ? "1 ad account" : `${p.ad_accounts} ad accounts`} ·
                        platform reported
                      </span>
                    </th>
                    <FigureCells context={data} keys={PLATFORM_COLUMNS} figures={p.figures} />
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        )}
        <ColumnDefinitions context={data} keys={PLATFORM_COLUMNS} />
      </section>
      <section aria-labelledby="report-channels" className={styles.section}>
        <h2 id="report-channels">Google Analytics channels</h2>
        <p className={styles.source}>
          Reported by Google Analytics, most sessions first. Never added to store or ad figures.
        </p>
        {data.analytics_channels.length === 0 ? (
          <p className={styles.muted}>
            {data.analytics_channels_missing
              ? `${figureReason(data.analytics_channels_missing as Figure)}.`
              : "No visits in this period."}
          </p>
        ) : (
          <ScrollTable label="Google Analytics channels">
            <table className={styles.table}>
              <caption>Google Analytics&apos; default channel groups.</caption>
              <thead>
                <tr>
                  <th scope="col">Channel</th>
                  <HeaderCells context={data} keys={CHANNEL_COLUMNS} />
                </tr>
              </thead>
              <tbody>
                {data.analytics_channels.map((c) => (
                  <tr key={c.channel}>
                    <th scope="row">{c.channel}</th>
                    <FigureCells context={data} keys={CHANNEL_COLUMNS} figures={c.figures} />
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        )}
        <ColumnDefinitions context={data} keys={CHANNEL_COLUMNS} />
      </section>
    </>
  );
}

function CampaignsReport({ data }: { data: Campaigns }) {
  // Two accounts can have campaigns of the same name: each row says whose it is.
  const accounts = new Map(
    data.sources.filter((s) => s.kind === "ad_account").map((s) => [s.id, s.name]),
  );
  return (
    <section aria-labelledby="report-campaigns" className={styles.section}>
      <h2 id="report-campaigns">Campaigns</h2>
      <PeriodLine data={data}>
        Every Google Ads and Meta campaign with its platform&apos;s own figures, and Google
        Analytics&apos; figures for the campaign with exactly the same name.
      </PeriodLine>
      {data.items.length === 0 ? (
        <p className={styles.muted}>No campaigns for this choice.</p>
      ) : (
        <ScrollTable label="Campaigns">
          <table className={styles.table}>
            <caption>
              Platform reported, in {data.reporting_currency}. The last three columns are Google
              Analytics&apos; figures for the campaign of the same name.
            </caption>
            <thead>
              <tr>
                <th scope="col">Campaign</th>
                <HeaderCells context={data} keys={CAMPAIGN_COLUMNS} />
                {CAMPAIGN_ANALYTICS.map((key) => (
                  <th key={key} scope="col" className={styles.num}>
                    {definitionsByKey(data.definitions)(key).label} (Google Analytics)
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
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </th>
                  <FigureCells context={data} keys={CAMPAIGN_COLUMNS} figures={c.figures} />
                  {c.analytics ? (
                    <FigureCells context={data} keys={CAMPAIGN_ANALYTICS} figures={c.analytics} />
                  ) : (
                    <td colSpan={CAMPAIGN_ANALYTICS.length} className={styles.missing}>
                      {figureReason(c.analytics_missing as Figure)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
      <ColumnDefinitions context={data} keys={[...CAMPAIGN_COLUMNS, ...CAMPAIGN_ANALYTICS]} />
      <p className={styles.muted}>
        Google Analytics figures are matched by exact campaign name: Google Ads campaigns with
        google / cpc traffic, Meta campaigns with facebook or instagram / paid or cpc traffic.
      </p>
    </section>
  );
}

function ProductsReport({ data }: { data: Products }) {
  const stores = new Map(
    data.sources.filter((s) => s.kind === "store").map((s) => [s.id, s.name ?? s.provider]),
  );
  const several = stores.size > 1;
  return (
    <section aria-labelledby="report-products" className={styles.section}>
      <h2 id="report-products">Products</h2>
      <PeriodLine data={data}>
        Every product sold in the period, most net sales first. Ad spend is not split by product.
      </PeriodLine>
      {data.other_currency_lines > 0 ? (
        <p className={styles.muted}>
          {data.other_currency_lines === 1
            ? "1 sold item is"
            : `${data.other_currency_lines} sold items are`}{" "}
          in a currency other than its store&apos;s and is left out; it is never added to these
          amounts.
        </p>
      ) : null}
      {data.items.length === 0 ? (
        <p className={styles.muted}>
          {data.items_missing
            ? `${figureReason(data.items_missing as Figure)}.`
            : "No products sold in this period."}
        </p>
      ) : (
        <ScrollTable label="Products">
          <table className={styles.table}>
            <caption>From your store platform, in {data.reporting_currency}.</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                {several ? <th scope="col">Store</th> : null}
                <HeaderCells context={data} keys={PRODUCT_COLUMNS} />
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={`${p.store_id}-${p.product_id ?? "unmatched"}`}>
                  <th scope="row">{p.title ?? "Items not matched to a product"}</th>
                  {several ? <td>{stores.get(p.store_id) ?? ""}</td> : null}
                  <FigureCells context={data} keys={PRODUCT_COLUMNS} figures={p.figures} />
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
      <ColumnDefinitions context={data} keys={PRODUCT_COLUMNS} />
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
  if (!query.data) return <p role="status">Loading figures…</p>;
  return (
    <>
      {render(query.data)}
      <Sources data={query.data} />
    </>
  );
}

type Args = { orgId: string; from: string; to: string; storeId: string | null };

function ChannelsData({ orgId, from, to, storeId }: Args) {
  const query = useChannels(orgId, from, to, storeId);
  return <Loaded query={query} render={(d) => <ChannelsReport data={d} />} />;
}

function CampaignsData({ orgId, from, to, storeId }: Args) {
  const query = useCampaigns(orgId, from, to, storeId);
  return <Loaded query={query} render={(d) => <CampaignsReport data={d} />} />;
}

function ProductsData({ orgId, from, to, storeId }: Args) {
  const query = useProductFigures(orgId, from, to, storeId);
  return <Loaded query={query} render={(d) => <ProductsReport data={d} />} />;
}

function ReportBody({ org, report }: { org: Organization; report: Report }) {
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
      {report === "channels" ? <ChannelsData {...args} /> : null}
      {report === "campaigns" ? <CampaignsData {...args} /> : null}
      {report === "products" ? <ProductsData {...args} /> : null}
    </>
  );
}

/** Channels, campaigns and products for a period (PLAN §9, task 6-08). */
export function ReportsPage() {
  const org = useCurrentOrganization();
  const [report, setReport] = useState<Report>("channels");
  return (
    <section aria-labelledby="reports-title">
      <PageHeading id="reports-title">Reports</PageHeading>
      <p className={styles.source}>
        Sales, ad spend and visits by channel, campaign and product.{" "}
        <Link href={`/orgs/${org.id}`}>Back to the Overview</Link>
      </p>
      <SelectField
        label="Report"
        options={REPORTS}
        value={report}
        onChange={(event) => setReport(event.target.value as Report)}
      />
      <ReportBody org={org} report={report} />
    </section>
  );
}
