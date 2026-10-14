"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canManageConnections } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatSyncedAt } from "@/lib/format/availability";

import { useResync, useStore } from "./api";
import { storeStatus } from "./labels";
import { RevenueView } from "./RevenueView";
import { SyncSummary } from "./StoresPage";
import styles from "./stores.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function StoreNotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="store-missing">
      <PageHeading id="store-missing">Store not found</PageHeading>
      <p>This store does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/stores`}>Back to stores</Link>
      </p>
    </section>
  );
}

type Notice = { tone: "success" | "error" | "info"; text: string; requestId: string | null };

function Detail({ storeId }: { storeId: string }) {
  const org = useCurrentOrganization();
  const store = useStore(org.id, storeId);
  const resync = useResync(org.id, storeId);
  const [notice, setNotice] = useState<Notice | null>(null);
  const manage = canManageConnections(org.role);

  if (store.error) {
    if (store.error instanceof ApiError && store.error.status === 404) return <StoreNotFound />;
    return <Alert tone="error">{messageFor(store.error)}</Alert>;
  }
  const s = store.data;
  if (!s) return <p role="status">Loading store…</p>;
  const status = storeStatus(s);
  const canSync = manage && s.linked && s.connection_status === "active";

  function syncNow() {
    resync.mutate(undefined, {
      onSuccess: () =>
        setNotice({
          tone: "success",
          text: "Full check started. Figures update when it finishes.",
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
    <section aria-labelledby="store-title">
      <p>
        <Link href={`/orgs/${org.id}/stores`}>← All stores</Link>
      </p>
      <PageHeading id="store-title">{s.name ?? s.domain}</PageHeading>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      <div className={styles.panel}>
        <p>
          <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
        </p>
        <p className={styles.muted} aria-live="polite">
          <SyncSummary store={s} />
        </p>
        <dl className={styles.facts}>
          <dt>Store address</dt>
          <dd>{s.domain}</dd>
          <dt>Currency</dt>
          <dd>{s.currency}</dd>
          <dt>Time zone</dt>
          <dd>{s.timezone}</dd>
          <dt>Order history from</dt>
          <dd>{formatSyncedAt(s.history_from)}</dd>
          <dt>Last full check</dt>
          <dd>{formatSyncedAt(s.sync.last_deep_reconciled_at)}</dd>
        </dl>
        {!s.linked ? (
          <p className={styles.muted}>
            This store is not linked, so it is not being updated. Link it again on its{" "}
            <Link href={`/orgs/${org.id}/connections`}>connection</Link>.
          </p>
        ) : null}
        {canSync ? (
          <p>
            <Button
              variant="secondary"
              busy={resync.isPending}
              disabled={s.sync.running}
              onClick={syncNow}
            >
              Sync now
            </Button>{" "}
            {s.sync.running ? <span className={styles.muted}>An update is running.</span> : null}
          </p>
        ) : null}
        <p>
          <Link href={`/orgs/${org.id}/stores/${s.id}/products`}>Products, stock and costs</Link>
        </p>
      </div>
      <RevenueView orgId={org.id} store={s} />
    </section>
  );
}

export function StorePage() {
  const params = useParams<{ storeId: string }>();
  const id = params.storeId ?? "";
  if (!UUID.test(id)) return <StoreNotFound />;
  return <Detail storeId={id} />;
}
