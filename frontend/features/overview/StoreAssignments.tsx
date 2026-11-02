"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { useAdAccounts } from "@/features/advertising/api";
import { providerName } from "@/features/advertising/labels";
import { useAnalyticsProperties } from "@/features/analytics/api";
import { analyticsProviderName } from "@/features/analytics/labels";
import type { Organization } from "@/features/organizations/api";
import { canUpdateOrganization } from "@/features/organizations/permissions";
import { useStores, type Store } from "@/features/stores/api";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useAssignStore, type AssignmentKind } from "./api";
import own from "./overview.module.css";

const ALL = "";

type Item = { id: string; name: string; storeId: string | null | undefined };
type Notice = { tone: "success" | "error"; text: string; requestId: string | null };

const storeLabel = (s: Store) => s.name ?? s.domain;

function AssignmentRow({
  org,
  kind,
  item,
  stores,
  manage,
  onDone,
}: {
  org: Organization;
  kind: AssignmentKind;
  item: Item;
  stores: readonly Store[];
  manage: boolean;
  onDone: (notice: Notice) => void;
}) {
  const assign = useAssignStore(org.id, kind);
  const current = item.storeId ?? ALL;
  const options = [
    { value: ALL, label: "All stores (the whole organization)" },
    ...stores.map((s) => ({ value: s.id, label: storeLabel(s) })),
  ];
  if (!manage) {
    const store = stores.find((s) => s.id === item.storeId);
    return (
      <>
        <dt>{item.name}</dt>
        <dd>{store ? storeLabel(store) : "All stores"}</dd>
      </>
    );
  }
  return (
    <SelectField
      label={`Store for ${item.name}`}
      options={options}
      value={current}
      disabled={assign.isPending}
      onChange={(event) => {
        const storeId = event.target.value || null;
        const target = stores.find((s) => s.id === storeId);
        assign.mutate(
          { id: item.id, storeId },
          {
            onSuccess: () =>
              onDone({
                tone: "success",
                text: `${item.name} now counts for ${target ? storeLabel(target) : "all stores"}.`,
                requestId: null,
              }),
            onError: (error) =>
              onDone({
                tone: "error",
                text: messageFor(error),
                requestId: error instanceof ApiError ? error.requestId : null,
              }),
          },
        );
      }}
    />
  );
}

/** Settings: which store each ad account and Google Analytics property belongs to (Q-6-1). */
export function StoreAssignments({ org }: { org: Organization }) {
  const stores = useStores(org.id);
  const accounts = useAdAccounts(org.id);
  const properties = useAnalyticsProperties(org.id);
  const [notice, setNotice] = useState<Notice | null>(null);
  const manage = canUpdateOrganization(org.role);

  const error = stores.error ?? accounts.error ?? properties.error;
  if (error) return <Alert tone="error">{messageFor(error)}</Alert>;
  if (!stores.data || !accounts.data || !properties.data) return <p role="status">Loading…</p>;
  const items: Array<{ kind: AssignmentKind; item: Item }> = [
    ...accounts.data.map((a) => ({
      kind: "ad_account" as const,
      item: {
        id: a.id,
        name: `${a.name ?? a.external_account_id} (${providerName(a.provider)})`,
        storeId: a.store_id,
      },
    })),
    ...properties.data.map((p) => ({
      kind: "analytics_property" as const,
      item: {
        id: p.id,
        name: `${p.name ?? p.external_property_id} (${analyticsProviderName(p.provider)})`,
        storeId: p.store_id,
      },
    })),
  ];

  let body;
  if (stores.data.length < 2) {
    body = (
      <p className={styles.muted}>
        {stores.data.length === 1
          ? "You have one store, so every ad account and Google Analytics property counts for it. Nothing to set."
          : "Connect a store first. With more than one store you can choose which store each ad account and property belongs to."}
      </p>
    );
  } else if (items.length === 0) {
    body = <p className={styles.muted}>No ad accounts or Google Analytics properties yet.</p>;
  } else {
    const rows = items.map(({ kind, item }) => (
      <AssignmentRow
        key={`${kind}-${item.id}`}
        org={org}
        kind={kind}
        item={item}
        stores={stores.data}
        manage={manage}
        onDone={setNotice}
      />
    ));
    body = (
      <>
        <p className={styles.muted}>
          Choose the store each one&apos;s figures belong to when you look at one store on the
          Overview. “All stores” counts it only for the whole organization.
          {manage ? " Changes are saved straight away." : ""}
        </p>
        {notice ? (
          <Alert tone={notice.tone} requestId={notice.requestId}>
            {notice.text}
          </Alert>
        ) : null}
        {manage ? (
          <div className={own.assignments}>{rows}</div>
        ) : (
          <dl className={styles.facts}>{rows}</dl>
        )}
      </>
    );
  }

  return (
    <div className={styles.panel}>
      <h2 id="store-assignments">Stores for ad accounts and properties</h2>
      {body}
    </div>
  );
}
