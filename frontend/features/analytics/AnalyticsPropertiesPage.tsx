"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import styles from "@/features/advertising/advertising.module.css";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { useAnalyticsProperties, type AnalyticsProperty } from "./api";
import { analyticsProviderName, analyticsSyncError, propertyStatus, SYNC_MODE } from "./labels";

/** One line about where the property's figures stand. */
export function PropertySyncSummary({ property }: { property: AnalyticsProperty }) {
  const { sync } = property;
  if (!property.first_import_completed_at) {
    if (property.status === "error") return <>{analyticsSyncError(sync.last_error_code)}</>;
    return (
      <>
        Importing 13 months of figures
        {sync.progress !== null && sync.progress !== undefined ? ` (${sync.progress}%)` : ""}
        {sync.waiting_for_allowance
          ? " — Google is limiting how much AdVegaX can read, so the import continues by itself later"
          : ""}
        …
      </>
    );
  }
  const parts = [`Last updated: ${formatSyncedAt(sync.last_quick_at)}`];
  if (sync.waiting_for_allowance)
    parts.push("Google is limiting how much AdVegaX can read — figures update by themselves later");
  else if (sync.running && sync.mode) parts.push(`${SYNC_MODE[sync.mode] ?? "Updating"} now`);
  if (sync.last_error_code) parts.push(analyticsSyncError(sync.last_error_code));
  return <>{parts.join(" · ")}</>;
}

export function AnalyticsPropertiesPage() {
  const org = useCurrentOrganization();
  const properties = useAnalyticsProperties(org.id);

  return (
    <section aria-labelledby="analytics-title">
      <PageHeading id="analytics-title">Analytics</PageHeading>
      {properties.error ? <Alert tone="error">{messageFor(properties.error)}</Alert> : null}
      {properties.isPending ? <p role="status">Loading analytics properties…</p> : null}
      {properties.data?.length === 0 ? (
        <div className={styles.panel}>
          <p>No analytics properties yet.</p>
          <p className={styles.muted}>
            Connect Google Analytics on the{" "}
            <Link href={`/orgs/${org.id}/connections`}>Connections</Link> page and link the
            properties this organization uses. AdVegaX then imports 13 months of daily visits, key
            events, purchases and revenue. It only reads them and never changes anything.
          </p>
        </div>
      ) : null}
      {properties.data?.length ? (
        <ul className={styles.list}>
          {properties.data.map((p) => {
            const status = propertyStatus(p);
            return (
              <li key={p.id} className={styles.card}>
                <div>
                  <p className={styles.cardTitle}>
                    <Link href={`/orgs/${org.id}/analytics/${p.id}`}>
                      {p.name ?? `Property ${p.external_property_id}`}
                    </Link>
                  </p>
                  <p className={styles.muted}>
                    {[
                      analyticsProviderName(p.provider),
                      p.account_name,
                      p.currency,
                      p.timezone.replaceAll("_", " "),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  <p className={styles.muted} aria-live="polite">
                    <PropertySyncSummary property={p} />
                  </p>
                </div>
                <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
