"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { useStores, type Store } from "./api";
import { storeStatus, syncError, SYNC_MODE } from "./labels";
import styles from "./stores.module.css";

/** One line about where the store's data stands. */
export function SyncSummary({ store }: { store: Store }) {
  const { sync } = store;
  if (!store.first_import_completed_at) {
    if (store.status === "error") return <>{syncError(sync.last_error_code)}</>;
    return (
      <>
        Importing your products and orders
        {sync.progress !== null && sync.progress !== undefined ? ` (${sync.progress}%)` : ""}…
      </>
    );
  }
  const parts = [`Last checked: ${formatSyncedAt(sync.last_reconciled_at)}`];
  if (sync.running && sync.mode) parts.push(`${SYNC_MODE[sync.mode] ?? "Updating"} now`);
  if (sync.last_error_code) parts.push(syncError(sync.last_error_code));
  return <>{parts.join(" · ")}</>;
}

export function StoresPage() {
  const org = useCurrentOrganization();
  const stores = useStores(org.id);

  return (
    <section aria-labelledby="stores-title">
      <PageHeading id="stores-title">Stores</PageHeading>
      {stores.error ? <Alert tone="error">{messageFor(stores.error)}</Alert> : null}
      {stores.isPending ? <p role="status">Loading stores…</p> : null}
      {stores.data?.length === 0 ? (
        <div className={styles.panel}>
          <p>No stores yet.</p>
          <p className={styles.muted}>
            Connect your store on the <Link href={`/orgs/${org.id}/connections`}>Connections</Link>{" "}
            page and link it. AdVegaX then imports its products and orders.
          </p>
        </div>
      ) : null}
      {stores.data?.length ? (
        <ul className={styles.list}>
          {stores.data.map((store) => {
            const status = storeStatus(store);
            return (
              <li key={store.id} className={styles.card}>
                <div>
                  <p className={styles.cardTitle}>
                    <Link href={`/orgs/${org.id}/stores/${store.id}`}>
                      {store.name ?? store.domain}
                    </Link>
                  </p>
                  <p className={styles.muted}>
                    {store.domain} · {store.currency}
                  </p>
                  <p className={styles.muted} aria-live="polite">
                    <SyncSummary store={store} />
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
