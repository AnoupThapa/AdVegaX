"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PageHeading } from "@/components/ui/PageHeading";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canManageConnections } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  jobFinished,
  keys,
  useConnection,
  useDisconnect,
  useJob,
  useProviders,
  useRediscover,
  useResources,
} from "./api";
import styles from "./connections.module.css";
import { connectError, connectionStatus } from "./labels";
import { ResourceRow, type RowNotice } from "./ResourceRow";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function NotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="conn-missing">
      <PageHeading id="conn-missing">Connection not found</PageHeading>
      <p>This connection does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/connections`}>Back to connections</Link>
      </p>
    </section>
  );
}

function Detail({ connectionId }: { connectionId: string }) {
  const org = useCurrentOrganization();
  const router = useRouter();
  const queryClient = useQueryClient();
  const connection = useConnection(org.id, connectionId);
  const providers = useProviders();
  const active = connection.data?.status === "active";
  const resources = useResources(org.id, connectionId, active);
  const disconnect = useDisconnect(org.id, connectionId);
  const rediscover = useRediscover(org.id, connectionId);
  const [discoveryJob, setDiscoveryJob] = useState<string | null>(null);
  const discovery = useJob(org.id, discoveryJob);
  const [confirming, setConfirming] = useState(false);
  const [notice, setNotice] = useState<RowNotice | null>(null);
  const manage = canManageConnections(org.role);

  const discoveryDone = jobFinished(discovery.data);
  useEffect(() => {
    if (discoveryDone)
      void queryClient.invalidateQueries({ queryKey: keys.resources(org.id, connectionId) });
  }, [discoveryDone, queryClient, org.id, connectionId]);

  if (connection.error) {
    if (connection.error instanceof ApiError && connection.error.status === 404)
      return <NotFound />;
    return <Alert tone="error">{messageFor(connection.error)}</Alert>;
  }
  const c = connection.data;
  if (!c) return <p role="status">Loading connection…</p>;

  const name = providers.data?.find((p) => p.code === c.provider)?.display_name ?? c.provider;
  const status = connectionStatus(c.status);
  const fail = (error: unknown) =>
    setNotice({
      tone: "error",
      text: messageFor(error),
      requestId: error instanceof ApiError ? error.requestId : null,
    });

  return (
    <section aria-labelledby="conn-title">
      <p>
        <Link href={`/orgs/${org.id}/connections`}>← All connections</Link>
      </p>
      <PageHeading id="conn-title">
        {name}
        {c.account_label ? ` — ${c.account_label}` : ""}
      </PageHeading>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      {c.status !== "active" && c.status !== "revoked" ? (
        <Alert tone="error">{connectError(c.last_error_code)}</Alert>
      ) : null}

      <dl className={`${styles.panel} ${styles.details}`}>
        <dt>Status</dt>
        <dd>
          <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
        </dd>
        <dt>Access granted</dt>
        <dd>
          {c.granted_scopes.length ? (
            c.granted_scopes.join(", ")
          ) : (
            <span className={styles.muted}>None reported</span>
          )}
        </dd>
        <dt>Connected</dt>
        <dd>
          {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
            new Date(c.created_at),
          )}
        </dd>
        {c.revoked_at ? (
          <>
            <dt>Disconnected</dt>
            <dd>
              {new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(c.revoked_at))}
            </dd>
          </>
        ) : null}
      </dl>

      <section aria-labelledby="accounts-title" className={styles.section}>
        <h2 id="accounts-title">Accounts found</h2>
        <p className={styles.muted}>
          Link the accounts this organization should use. Nothing is used until it is linked.
        </p>
        {resources.error ? <Alert tone="error">{messageFor(resources.error)}</Alert> : null}
        {resources.isPending ? <p role="status">Loading accounts…</p> : null}
        {resources.data?.length === 0 ? (
          <p role="status">
            {resources.stillLooking
              ? "Looking for accounts… this can take a moment."
              : active && manage
                ? "No accounts found yet. If you expected some, use “Check for new accounts”, or check what access was granted on the platform."
                : "No accounts were found."}
          </p>
        ) : null}
        {discovery.data?.status === "failed" || discovery.data?.status === "dead" ? (
          <Alert tone="error">
            The check for new accounts did not finish —{" "}
            {connectError(discovery.data.last_error_code)}
          </Alert>
        ) : null}
        {discovery.error ? (
          <Alert tone="error">
            Could not follow the check for new accounts — {messageFor(discovery.error)}
          </Alert>
        ) : null}
        {resources.data?.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <caption>
                {resources.data.length === 1 ? "1 account" : `${resources.data.length} accounts`}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Account</th>
                  <th scope="col">Currency · time zone</th>
                  <th scope="col">Linked</th>
                  <th scope="col">Last synced</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {resources.data.map((r) => (
                  <ResourceRow
                    key={r.id}
                    orgId={org.id}
                    connectionId={c.id}
                    resource={r}
                    canManage={manage}
                    connectionActive={active}
                    onNotice={setNotice}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {manage && active ? (
          <p>
            <Button
              variant="secondary"
              busy={
                rediscover.isPending ||
                (discoveryJob !== null && !discoveryDone && !discovery.error)
              }
              onClick={() =>
                rediscover.mutate(undefined, {
                  onSuccess: (job) => {
                    setDiscoveryJob(job.id);
                    setNotice({
                      tone: "success",
                      text: "Checking the platform for accounts…",
                      requestId: null,
                    });
                  },
                  onError: fail,
                })
              }
            >
              Check for new accounts
            </Button>
          </p>
        ) : null}
      </section>

      {manage && c.status !== "revoked" ? (
        <section aria-labelledby="disconnect-title" className={styles.panel}>
          <h2 id="disconnect-title">Disconnect</h2>
          <p className={styles.muted}>
            Removes AdVegaX&apos;s access at the platform where possible, deletes the stored sign-in
            details and unlinks every account. History is kept.
          </p>
          <Button variant="danger" onClick={() => setConfirming(true)}>
            Disconnect {name}
          </Button>
        </section>
      ) : null}
      {!manage ? (
        <p className={styles.muted}>Only owners, admins and managers can change connections.</p>
      ) : null}

      <ConfirmDialog
        open={confirming}
        title={`Disconnect ${name}?`}
        confirmLabel="Disconnect"
        busy={disconnect.isPending}
        onConfirm={() =>
          disconnect.mutate(undefined, {
            onSuccess: () => router.push(`/orgs/${org.id}/connections`),
            onError: (error) => {
              setConfirming(false);
              fail(error);
            },
          })
        }
        onCancel={() => setConfirming(false)}
      >
        <p>
          Linked accounts will be unlinked and data will stop updating. You can connect again later.
        </p>
        {c.provider === "shopify" ? (
          <p>
            AdVegaX deletes its access here. To remove the app completely, also uninstall it in your
            Shopify admin (Settings → Apps).
          </p>
        ) : null}
        {c.provider === "woocommerce" ? (
          <p>
            AdVegaX deletes its access key here. To remove it from your store too, revoke the
            AdVegaX key in WordPress (WooCommerce → Settings → Advanced → REST API).
          </p>
        ) : null}
      </ConfirmDialog>
    </section>
  );
}

export function ConnectionDetailPage() {
  const params = useParams<{ connectionId: string }>();
  const id = params.connectionId ?? "";
  if (!UUID.test(id)) return <NotFound />;
  return <Detail connectionId={id} />;
}
