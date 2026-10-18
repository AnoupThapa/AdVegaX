"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { addDays, formatDay } from "@/features/stores/dates";
import { ApiError, messageFor } from "@/lib/api/errors";

import { NotSyncedNotice, UUID } from "./AdAccountPage";
import { useAdCampaign, type AdCampaignDetail } from "./api";
import styles from "./advertising.module.css";
import { FigureTiles, figureText, PERIODS, type Currency } from "./Figures";
import { budgetText, entityStatus, platformType, reportedBy } from "./labels";

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function CampaignNotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="campaign-missing">
      <PageHeading id="campaign-missing">Campaign not found</PageHeading>
      <p>This campaign does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/advertising`}>Back to advertising</Link>
      </p>
    </section>
  );
}

function daysBetween(from: string, to: string): number {
  return (
    Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000) + 1
  );
}

function AdGroups({ data, currency }: { data: AdCampaignDetail; currency: Currency }) {
  const t = figureText(currency);
  if (data.ad_groups.length === 0) {
    return (
      <p className={styles.muted}>
        This campaign has no ad groups. Some campaign types, such as Performance Max, report figures
        only for the whole campaign.
      </p>
    );
  }
  return (
    <>
      {data.ad_groups.map((group) => {
        const status = entityStatus(group.status);
        return (
          <section
            key={group.id}
            aria-labelledby={`group-${group.id}`}
            className={`${styles.panel} ${styles.section}`}
          >
            <h3 id={`group-${group.id}`} className={styles.groupTitle}>
              {group.name}{" "}
              <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
            </h3>
            <p className={styles.muted}>
              {platformType(group.platform_type)}
              {group.budget ? ` · Budget: ${budgetText(group.budget, t.money)}` : ""}
            </p>
            <FigureTiles
              figures={group.figures}
              currency={currency}
              label={`Totals for ${group.name}`}
            />
            {group.ads.length ? (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption>Ads in {group.name}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Ad</th>
                      <th scope="col">Status</th>
                      <th scope="col" className={styles.num}>
                        Spend
                      </th>
                      <th scope="col" className={styles.num}>
                        Clicks
                      </th>
                      <th scope="col" className={styles.num}>
                        Impressions
                      </th>
                      <th scope="col" className={styles.num}>
                        Conversions
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.ads.map((ad) => {
                      const adStatus = entityStatus(ad.status);
                      const missing = ad.figures.availability !== "available";
                      const cell = `${styles.num} ${missing ? styles.missing : ""}`;
                      return (
                        <tr key={ad.id}>
                          <th scope="row">
                            {ad.name ?? `Ad ${ad.external_id}`}
                            <br />
                            <span className={styles.muted}>{platformType(ad.platform_type)}</span>
                          </th>
                          <td>
                            <span className={`${styles.status} ${styles[adStatus.tone]}`}>
                              {adStatus.label}
                            </span>
                          </td>
                          <td className={cell}>{t.cost(ad.figures)}</td>
                          <td className={cell}>{t.clicks(ad.figures)}</td>
                          <td className={cell}>{t.impressions(ad.figures)}</td>
                          <td className={cell}>{t.conversions(ad.figures)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className={styles.muted}>No ads in this ad group.</p>
            )}
          </section>
        );
      })}
    </>
  );
}

function Detail({ campaignId }: { campaignId: string }) {
  const org = useCurrentOrganization();
  const search = useSearchParams();
  const fromParam = search.get("from");
  const toParam = search.get("to");
  const valid = fromParam && toParam && DAY.test(fromParam) && DAY.test(toParam);
  const [range, setRange] = useState<{ from: string; to: string } | null>(
    valid ? { from: fromParam, to: toParam } : null,
  );
  const campaign = useAdCampaign(org.id, campaignId, range?.from ?? null, range?.to ?? null);

  if (campaign.error) {
    if (campaign.error instanceof ApiError && campaign.error.status === 404)
      return <CampaignNotFound />;
    return <Alert tone="error">{messageFor(campaign.error)}</Alert>;
  }
  const c = campaign.data;
  if (!c) return <p role="status">Loading campaign…</p>;
  const currency = { currency: c.currency, minorUnits: c.currency_minor_units };
  const t = figureText(currency);
  const status = entityStatus(c.status);
  const span = String(daysBetween(c.from_day, c.to_day));
  const options = PERIODS.some((p) => p.value === span)
    ? PERIODS
    : [...PERIODS, { value: span, label: `${formatDay(c.from_day)} – ${formatDay(c.to_day)}` }];

  return (
    <section aria-labelledby="campaign-title">
      <p>
        <Link href={`/orgs/${org.id}/advertising/${c.ad_account_id}`}>← Ad account</Link>
      </p>
      <PageHeading id="campaign-title">{c.name}</PageHeading>
      <p className={styles.source}>
        {reportedBy(c.provider)}. Amounts in {c.currency}.
      </p>
      <div className={styles.panel}>
        <p>
          <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
        </p>
        <dl className={styles.facts}>
          <dt>Type</dt>
          <dd>{platformType(c.platform_type)}</dd>
          <dt>Bidding</dt>
          <dd>{platformType(c.bidding_strategy_type)}</dd>
          <dt>Budget</dt>
          <dd>
            {budgetText(c.budget, t.money)}
            {c.budget?.name ? ` — ${c.budget.name}` : ""}
          </dd>
          <dt>Runs</dt>
          <dd>
            {c.start_date ? `From ${formatDay(c.start_date)}` : "Start not given"}
            {c.end_date ? ` to ${formatDay(c.end_date)}` : " · no end date"}
          </dd>
        </dl>
      </div>
      <section aria-labelledby="campaign-figures" className={styles.section}>
        <h2 id="campaign-figures">Performance</h2>
        <div className={styles.toolbar}>
          <SelectField
            label="Period"
            options={options}
            value={span}
            onChange={(event) =>
              setRange({ from: addDays(c.to_day, -(Number(event.target.value) - 1)), to: c.to_day })
            }
          />
        </div>
        {c.figures.availability !== "available" ? (
          <NotSyncedNotice syncedFrom={c.synced_from} />
        ) : null}
        <FigureTiles figures={c.figures} currency={currency} label="Totals for the period" />
      </section>
      <section aria-labelledby="campaign-groups" className={styles.section}>
        <h2 id="campaign-groups">Ad groups and ads</h2>
        <p className={styles.source}>
          {reportedBy(c.provider)}. Each level has its own figures; they are not added together.
        </p>
        <AdGroups data={c} currency={currency} />
      </section>
    </section>
  );
}

export function CampaignPage() {
  const params = useParams<{ campaignId: string }>();
  const id = params.campaignId ?? "";
  if (!UUID.test(id)) return <CampaignNotFound />;
  return <Detail campaignId={id} />;
}
