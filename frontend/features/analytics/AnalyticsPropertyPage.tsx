"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { PERIODS } from "@/features/advertising/Figures";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canManageConnections } from "@/features/organizations/permissions";
import { addDays, formatDay, todayIn } from "@/features/stores/dates";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { PropertySyncSummary } from "./AnalyticsPropertiesPage";
import {
  useAnalyticsMetrics,
  useAnalyticsProperty,
  useAnalyticsResync,
  type AnalyticsMetrics,
  type AnalyticsProperty,
  type Breakdown,
} from "./api";
import { AnalyticsDailyTable, AnalyticsTiles, BreakdownTable, type Currency } from "./Figures";
import {
  BREAKDOWNS,
  analyticsProviderName,
  propertyHealth,
  propertyStatus,
  qualityNotes,
  reportedBy,
} from "./labels";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function PropertyNotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="property-missing">
      <PageHeading id="property-missing">Property not found</PageHeading>
      <p>This analytics property does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/analytics`}>Back to analytics</Link>
      </p>
    </section>
  );
}

function NotSyncedNotice({ syncedFrom }: { syncedFrom: string | null | undefined }) {
  return (
    <Alert tone="info">
      {syncedFrom
        ? `Part of this period is before ${formatDay(syncedFrom)}, the first day AdVegaX has figures for, so period totals are not shown. Choose a shorter period.`
        : "This property's figures are still being imported. They appear when the import finishes."}
    </Alert>
  );
}

/** Processing and data-quality notes for the period, in plain words (Q-5-6, Q-5-8). */
function PeriodNotes({ data }: { data: AnalyticsMetrics }) {
  const notes = qualityNotes(data.totals.quality);
  const processing = data.to_day >= data.processing_from;
  if (!processing && notes.length === 0) return null;
  return (
    <ul className={styles.muted} aria-label="Notes about these figures">
      {processing ? (
        <li>
          Days from {formatDay(data.processing_from)} are still being processed by Google and can
          change. AdVegaX reads them again by itself.
        </li>
      ) : null}
      {notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  );
}

function Performance({ orgId, property }: { orgId: string; property: AnalyticsProperty }) {
  const [period, setPeriod] = useState<string>("30");
  const [view, setView] = useState<Breakdown>("channel");
  const to = todayIn(property.timezone);
  const from = addDays(to, -(Number(period) - 1));
  const totals = useAnalyticsMetrics(orgId, property.id, "total", from, to);
  const breakdown = useAnalyticsMetrics(orgId, property.id, view, from, to);
  const currency: Currency = {
    currency: property.currency,
    minorUnits: property.currency_minor_units,
  };

  return (
    <>
      <section aria-labelledby="analytics-figures" className={styles.section}>
        <h2 id="analytics-figures">Visits and sales</h2>
        <p className={styles.source}>
          {reportedBy(property.provider)}. Amounts in {property.currency}. AdVegaX does not compare
          them with store sales or ad spend yet.
        </p>
        <div className={styles.toolbar}>
          <SelectField
            label="Period"
            options={PERIODS}
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          />
        </div>
        {totals.error ? <Alert tone="error">{messageFor(totals.error)}</Alert> : null}
        {totals.isPending ? <p role="status">Loading figures…</p> : null}
        {totals.data ? (
          <>
            {totals.data.totals.availability !== "available" ? (
              <NotSyncedNotice syncedFrom={totals.data.synced_from} />
            ) : null}
            <PeriodNotes data={totals.data} />
            <AnalyticsTiles
              figures={totals.data.totals}
              currency={currency}
              label="Totals for the period"
            />
            <h3>By day</h3>
            <AnalyticsDailyTable data={totals.data} currency={currency} />
          </>
        ) : null}
      </section>
      <section aria-labelledby="analytics-sources" className={styles.section}>
        <h2 id="analytics-sources">Where visits came from</h2>
        <p className={styles.source}>{reportedBy(property.provider)}.</p>
        <div className={styles.toolbar}>
          <SelectField
            label="Show"
            options={BREAKDOWNS}
            value={view}
            onChange={(event) => setView(event.target.value as Breakdown)}
          />
        </div>
        {breakdown.error ? <Alert tone="error">{messageFor(breakdown.error)}</Alert> : null}
        {breakdown.isPending ? <p role="status">Loading…</p> : null}
        {breakdown.data ? (
          breakdown.data.totals.availability !== "available" ? (
            <p className={styles.muted}>Not available for this period.</p>
          ) : (
            <BreakdownTable data={breakdown.data} currency={currency} />
          )
        ) : null}
      </section>
    </>
  );
}

type Notice = { tone: "success" | "error" | "info"; text: string; requestId: string | null };

function Detail({ propertyId }: { propertyId: string }) {
  const org = useCurrentOrganization();
  const property = useAnalyticsProperty(org.id, propertyId);
  const resync = useAnalyticsResync(org.id, propertyId);
  const [notice, setNotice] = useState<Notice | null>(null);
  const manage = canManageConnections(org.role);

  if (property.error) {
    if (property.error instanceof ApiError && property.error.status === 404)
      return <PropertyNotFound />;
    return <Alert tone="error">{messageFor(property.error)}</Alert>;
  }
  const p = property.data;
  if (!p) return <p role="status">Loading property…</p>;
  const status = propertyStatus(p);
  const health = propertyHealth(p.health?.code);
  const canSync = manage && p.linked && p.connection_status === "active";

  function syncNow() {
    resync.mutate(undefined, {
      onSuccess: () =>
        setNotice({
          tone: "success",
          text: "Update started: the last 14 days are read again.",
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
    <section aria-labelledby="property-title">
      <p>
        <Link href={`/orgs/${org.id}/analytics`}>← All analytics properties</Link>
      </p>
      <PageHeading id="property-title">
        {p.name ?? `Property ${p.external_property_id}`}
      </PageHeading>
      <p className={styles.source}>
        {analyticsProviderName(p.provider)} property {p.external_property_id}
      </p>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      {p.linked && p.connection_status !== "active" ? (
        <Alert tone="error">
          The Google Analytics connection needs reconnecting, so this property is not being updated.{" "}
          {manage ? (
            <Link href={`/orgs/${org.id}/connections`}>Reconnect Google Analytics</Link>
          ) : (
            "Ask an owner or admin of this organization to reconnect."
          )}
        </Alert>
      ) : null}
      {health ? (
        <section aria-labelledby="property-health" className={styles.health}>
          <h2 id="property-health">{health.title}</h2>
          <p>{health.fix}</p>
          {p.health?.checked_at ? (
            <p className={styles.muted}>Checked {formatSyncedAt(p.health.checked_at)}.</p>
          ) : null}
        </section>
      ) : null}
      <div className={styles.panel}>
        <p>
          <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
        </p>
        <p className={styles.muted} aria-live="polite">
          <PropertySyncSummary property={p} />
        </p>
        <dl className={styles.facts}>
          {p.account_name ? (
            <>
              <dt>Analytics account</dt>
              <dd>{p.account_name}</dd>
            </>
          ) : null}
          <dt>Currency</dt>
          <dd>{p.currency}</dd>
          <dt>Time zone</dt>
          <dd>{p.timezone.replaceAll("_", " ")}</dd>
          <dt>Figures from</dt>
          <dd>{p.history_from ? formatDay(p.history_from) : "Not synced yet"}</dd>
          <dt>Last 14 days re-checked</dt>
          <dd>{formatSyncedAt(p.sync.last_nightly_at)}</dd>
          <dt>Last 90 days re-checked</dt>
          <dd>{formatSyncedAt(p.sync.last_weekly_at)}</dd>
        </dl>
        {!p.linked ? (
          <p className={styles.muted}>
            This property is not linked, so it is not being updated. Its figures stay readable. Link
            it again on its <Link href={`/orgs/${org.id}/connections`}>connection</Link>.
          </p>
        ) : null}
        {canSync ? (
          <p>
            <Button
              variant="secondary"
              busy={resync.isPending}
              disabled={p.sync.running}
              onClick={syncNow}
            >
              Sync now
            </Button>{" "}
            {p.sync.running ? <span className={styles.muted}>An update is running.</span> : null}
          </p>
        ) : null}
      </div>
      <Performance orgId={org.id} property={p} />
    </section>
  );
}

export function AnalyticsPropertyPage() {
  const params = useParams<{ propertyId: string }>();
  const id = params.propertyId ?? "";
  if (!UUID.test(id)) return <PropertyNotFound />;
  return <Detail propertyId={id} />;
}
