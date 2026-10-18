"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canManageConnections } from "@/features/organizations/permissions";
import { addDays, formatDay, todayIn } from "@/features/stores/dates";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { AdSyncSummary } from "./AdAccountsPage";
import {
  useAdAccount,
  useAdCampaigns,
  useAdDailyMetrics,
  useAdResync,
  type AdAccount,
  type AdCampaignList,
} from "./api";
import styles from "./advertising.module.css";
import { DailyTable, FigureTiles, figureText, PERIODS, type Currency } from "./Figures";
import {
  adAccountStatus,
  adHealth,
  budgetText,
  entityStatus,
  platformType,
  providerName,
  reportedBy,
} from "./labels";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function AdAccountNotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="ad-missing">
      <PageHeading id="ad-missing">Ad account not found</PageHeading>
      <p>This ad account does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/advertising`}>Back to advertising</Link>
      </p>
    </section>
  );
}

/** Why a period has no totals, in plain words. */
export function NotSyncedNotice({ syncedFrom }: { syncedFrom: string | null | undefined }) {
  return (
    <Alert tone="info">
      {syncedFrom
        ? `Part of this period is before ${formatDay(syncedFrom)}, the first day AdVegaX has figures for, so period totals are not shown. Choose a shorter period.`
        : "This ad account's figures are still being imported. They appear when the import finishes."}
    </Alert>
  );
}

function CampaignTable({
  orgId,
  data,
  currency,
}: {
  orgId: string;
  data: AdCampaignList;
  currency: Currency;
}) {
  const t = figureText(currency);
  if (data.items.length === 0) return <p>No campaigns in this ad account yet.</p>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>
          Campaigns with their own figures for the period. Removed campaigns are kept so their
          history stays readable.
        </caption>
        <thead>
          <tr>
            <th scope="col">Campaign</th>
            <th scope="col">Status</th>
            <th scope="col">Budget</th>
            <th scope="col" className={styles.num}>
              Spend
            </th>
            <th scope="col" className={styles.num}>
              Clicks
            </th>
            <th scope="col" className={styles.num}>
              Conversions
            </th>
            <th scope="col" className={styles.num}>
              Click-through rate
            </th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((c) => {
            const status = entityStatus(c.status);
            const missing = c.figures.availability !== "available";
            const cell = `${styles.num} ${missing ? styles.missing : ""}`;
            return (
              <tr key={c.id}>
                <th scope="row">
                  <Link
                    href={`/orgs/${orgId}/advertising/campaigns/${c.id}?from=${data.from_day}&to=${data.to_day}`}
                  >
                    {c.name}
                  </Link>
                  <br />
                  <span className={styles.muted}>{platformType(c.platform_type)}</span>
                </th>
                <td>
                  <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
                </td>
                <td>{budgetText(c.budget, t.money)}</td>
                <td className={cell}>{t.cost(c.figures)}</td>
                <td className={cell}>{t.clicks(c.figures)}</td>
                <td className={cell}>{t.conversions(c.figures)}</td>
                <td className={cell}>{t.ctr(c.figures)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Performance({ orgId, account }: { orgId: string; account: AdAccount }) {
  const [period, setPeriod] = useState<string>("30");
  const to = todayIn(account.timezone);
  const from = addDays(to, -(Number(period) - 1));
  const metrics = useAdDailyMetrics(orgId, account.id, from, to);
  const campaigns = useAdCampaigns(orgId, account.id, from, to);
  const currency = { currency: account.currency, minorUnits: account.currency_minor_units };

  return (
    <>
      <section aria-labelledby="ads-performance" className={styles.section}>
        <h2 id="ads-performance">Performance</h2>
        <p className={styles.source}>
          {reportedBy(account.provider)}. Amounts in {account.currency}. AdVegaX does not compare
          them with store sales yet.
        </p>
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
              <NotSyncedNotice syncedFrom={metrics.data.synced_from} />
            ) : null}
            <FigureTiles
              figures={metrics.data.totals}
              currency={currency}
              label="Totals for the period"
            />
            <h3>By day</h3>
            <DailyTable data={metrics.data} currency={currency} />
          </>
        ) : null}
      </section>
      <section aria-labelledby="ads-campaigns" className={styles.section}>
        <h2 id="ads-campaigns">Campaigns</h2>
        <p className={styles.source}>{reportedBy(account.provider)}.</p>
        {campaigns.error ? <Alert tone="error">{messageFor(campaigns.error)}</Alert> : null}
        {campaigns.isPending ? <p role="status">Loading campaigns…</p> : null}
        {campaigns.data ? (
          <CampaignTable orgId={orgId} data={campaigns.data} currency={currency} />
        ) : null}
      </section>
    </>
  );
}

type Notice = { tone: "success" | "error" | "info"; text: string; requestId: string | null };

function Detail({ accountId }: { accountId: string }) {
  const org = useCurrentOrganization();
  const account = useAdAccount(org.id, accountId);
  const resync = useAdResync(org.id, accountId);
  const [notice, setNotice] = useState<Notice | null>(null);
  const manage = canManageConnections(org.role);

  if (account.error) {
    if (account.error instanceof ApiError && account.error.status === 404)
      return <AdAccountNotFound />;
    return <Alert tone="error">{messageFor(account.error)}</Alert>;
  }
  const a = account.data;
  if (!a) return <p role="status">Loading ad account…</p>;
  const status = adAccountStatus(a);
  const health = adHealth(a.health?.code);
  const canSync = manage && a.linked && a.connection_status === "active";

  function syncNow() {
    resync.mutate(undefined, {
      onSuccess: () =>
        setNotice({
          tone: "success",
          text: "Update started: campaigns and the last 30 days are read again.",
          requestId: null,
        }),
      onError: (error) =>
        setNotice({
          tone: "error",
          text: messageFor(error),
          requestId: error instanceof ApiError ? error.requestId : null,
        }),
    });
  }

  return (
    <section aria-labelledby="ad-title">
      <p>
        <Link href={`/orgs/${org.id}/advertising`}>← All ad accounts</Link>
      </p>
      <PageHeading id="ad-title">{a.name ?? a.external_account_id}</PageHeading>
      <p className={styles.source}>
        {providerName(a.provider)} ad account {a.external_account_id}
      </p>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      {health ? (
        <section aria-labelledby="ad-health" className={styles.health}>
          <h2 id="ad-health">{health.title}</h2>
          <p>{health.fix}</p>
          {a.health?.checked_at ? (
            <p className={styles.muted}>Checked {formatSyncedAt(a.health.checked_at)}.</p>
          ) : null}
        </section>
      ) : null}
      <div className={styles.panel}>
        <p>
          <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
        </p>
        <p className={styles.muted} aria-live="polite">
          <AdSyncSummary account={a} />
        </p>
        <dl className={styles.facts}>
          {a.group_path ? (
            <>
              <dt>Reached through</dt>
              <dd>{a.group_path.replaceAll(" > ", " › ")}</dd>
            </>
          ) : null}
          <dt>Currency</dt>
          <dd>{a.currency}</dd>
          <dt>Time zone</dt>
          <dd>{a.timezone.replaceAll("_", " ")}</dd>
          <dt>Figures from</dt>
          <dd>{a.history_from ? formatDay(a.history_from) : "Not synced yet"}</dd>
          <dt>Last 30 days re-checked</dt>
          <dd>{formatSyncedAt(a.sync.last_nightly_at)}</dd>
          <dt>Last 90 days re-checked</dt>
          <dd>{formatSyncedAt(a.sync.last_weekly_at)}</dd>
        </dl>
        {!a.linked ? (
          <p className={styles.muted}>
            This ad account is not linked, so it is not being updated. Its figures stay readable.
            Link it again on its <Link href={`/orgs/${org.id}/connections`}>connection</Link>.
          </p>
        ) : null}
        {canSync ? (
          <p>
            <Button
              variant="secondary"
              busy={resync.isPending}
              disabled={a.sync.running}
              onClick={syncNow}
            >
              Sync now
            </Button>{" "}
            {a.sync.running ? <span className={styles.muted}>An update is running.</span> : null}
          </p>
        ) : null}
      </div>
      <Performance orgId={org.id} account={a} />
    </section>
  );
}

export function AdAccountPage() {
  const params = useParams<{ adAccountId: string }>();
  const id = params.adAccountId ?? "";
  if (!UUID.test(id)) return <AdAccountNotFound />;
  return <Detail accountId={id} />;
}
