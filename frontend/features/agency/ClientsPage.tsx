"use client";

import Link from "next/link";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import styles from "@/features/advertising/advertising.module.css";
import { FigureCell } from "@/features/overview/Shared";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { roleLabel } from "@/features/organizations/permissions";
import { messageFor } from "@/lib/api/errors";

import { useClients } from "./api";

const BILLING: Record<string, string> = {
  off: "—",
  complimentary: "Complimentary",
  trialing: "Trial",
  active: "Paid",
  past_due: "Payment failed",
  read_only: "Read-only",
};

/** The agency's clients (Phase 14): each on its own row, in its own currency — no totals. */
export function ClientsPage() {
  const org = useCurrentOrganization();
  const clients = useClients(org.id);
  return (
    <section aria-labelledby="clients-title">
      <PageHeading id="clients-title">Clients</PageHeading>
      <p className={styles.muted}>
        Each client is shown on its own, in its own currency, for the last 30 days. Figures are
        never added across clients.
      </p>
      {clients.error ? <Alert tone="error">{messageFor(clients.error)}</Alert> : null}
      {clients.isPending ? <p role="status">Loading…</p> : null}
      {clients.data?.length === 0 ? (
        <p role="status">No client has given this organization access yet.</p>
      ) : null}
      {clients.data?.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>Clients</caption>
            <thead>
              <tr>
                <th scope="col">Client</th>
                <th scope="col">Your role</th>
                <th scope="col">Plan</th>
                <th scope="col" className={styles.num}>
                  Ad spend
                </th>
                <th scope="col" className={styles.num}>
                  Net sales
                </th>
                <th scope="col" className={styles.num}>
                  Open recommendations
                </th>
                <th scope="col" className={styles.num}>
                  Connections needing attention
                </th>
              </tr>
            </thead>
            <tbody>
              {clients.data.map((c) => {
                const currency = { currency: c.currency, minorUnits: 2 };
                return (
                  <tr key={c.organization_id}>
                    <th scope="row">
                      <Link href={`/orgs/${c.organization_id}`}>{c.name}</Link>
                    </th>
                    <td>{roleLabel(c.role)}</td>
                    <td>{BILLING[c.billing_status] ?? c.billing_status}</td>
                    <FigureCell figure={c.ad_spend} unit="money" currency={currency} />
                    <FigureCell figure={c.net_sales} unit="money" currency={currency} />
                    <td className={styles.num}>{c.open_recommendations}</td>
                    <td className={styles.num}>{c.connections_needing_attention}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
