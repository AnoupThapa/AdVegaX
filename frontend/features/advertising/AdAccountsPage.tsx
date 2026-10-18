"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { useAdAccounts, type AdAccount } from "./api";
import styles from "./advertising.module.css";
import { adAccountStatus, adSyncError, providerName, SYNC_MODE } from "./labels";

/** One line about where the ad account's figures stand. */
export function AdSyncSummary({ account }: { account: AdAccount }) {
  const { sync } = account;
  if (!account.first_import_completed_at) {
    if (account.status === "error") return <>{adSyncError(sync.last_error_code)}</>;
    return (
      <>
        Importing campaigns and 13 months of figures
        {sync.progress !== null && sync.progress !== undefined ? ` (${sync.progress}%)` : ""}…
      </>
    );
  }
  const parts = [`Last updated: ${formatSyncedAt(sync.last_quick_at)}`];
  if (sync.waiting_for_allowance)
    parts.push("Waiting for Google's daily limit — figures update by themselves later");
  else if (sync.running && sync.mode) parts.push(`${SYNC_MODE[sync.mode] ?? "Updating"} now`);
  if (sync.last_error_code) parts.push(adSyncError(sync.last_error_code));
  return <>{parts.join(" · ")}</>;
}

export function AdAccountsPage() {
  const org = useCurrentOrganization();
  const accounts = useAdAccounts(org.id);

  return (
    <section aria-labelledby="ads-title">
      <PageHeading id="ads-title">Advertising</PageHeading>
      {accounts.error ? <Alert tone="error">{messageFor(accounts.error)}</Alert> : null}
      {accounts.isPending ? <p role="status">Loading ad accounts…</p> : null}
      {accounts.data?.length === 0 ? (
        <div className={styles.panel}>
          <p>No ad accounts yet.</p>
          <p className={styles.muted}>
            Connect Google Ads on the <Link href={`/orgs/${org.id}/connections`}>Connections</Link>{" "}
            page and link the ad accounts this organization uses. AdVegaX then imports their
            campaigns and 13 months of figures. It only reads them and never changes anything.
          </p>
        </div>
      ) : null}
      {accounts.data?.length ? (
        <ul className={styles.list}>
          {accounts.data.map((account) => {
            const status = adAccountStatus(account);
            return (
              <li key={account.id} className={styles.card}>
                <div>
                  <p className={styles.cardTitle}>
                    <Link href={`/orgs/${org.id}/advertising/${account.id}`}>
                      {account.name ?? account.external_account_id}
                    </Link>
                  </p>
                  <p className={styles.muted}>
                    {providerName(account.provider)} · {account.currency} ·{" "}
                    {account.timezone.replaceAll("_", " ")}
                  </p>
                  <p className={styles.muted} aria-live="polite">
                    <AdSyncSummary account={account} />
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
