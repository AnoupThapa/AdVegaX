"use client";

import Link from "next/link";

import { PageHeading } from "@/components/ui/PageHeading";

import { useCurrentOrganization } from "./OrganizationShell";
import styles from "./organizations.module.css";
import { canManageMembers, roleLabel } from "./permissions";

export function OrganizationOverview() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="org-title">
      <PageHeading id="org-title">{org.name}</PageHeading>
      <p className={styles.muted}>
        Your role: <span className={styles.badge}>{roleLabel(org.role)}</span>
      </p>
      <div className={styles.panel}>
        <h2>Nothing to show yet</h2>
        <p>
          Sales, advertising and profit reports will appear here in a later release, once your store
          and ad accounts are connected.
        </p>
        <p>
          <Link href={`/orgs/${org.id}/connections`}>See connections</Link>
        </p>
      </div>
      <div className={styles.panel}>
        <h2>Your team</h2>
        <p>
          {canManageMembers(org.role)
            ? "Invite people to work with you and choose what each of them can do."
            : "See who else works in this organization."}
        </p>
        <p>
          <Link href={`/orgs/${org.id}/members`}>
            {canManageMembers(org.role) ? "Manage members" : "View members"}
          </Link>
        </p>
      </div>
    </section>
  );
}
