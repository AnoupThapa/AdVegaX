"use client";

import Link from "next/link";

import type { SessionUser } from "@/features/auth/session";

import styles from "./organizations.module.css";
import { roleLabel } from "./permissions";

/** The signed-in home page: the user's organizations and a way to create one. */
export function OrganizationList({ user }: { user: SessionUser }) {
  const memberships = user.memberships ?? [];
  return (
    <section aria-labelledby="orgs-title">
      <h2 id="orgs-title">Your organizations</h2>
      {memberships.length ? (
        <ul className={styles.orgList}>
          {memberships.map((m) => (
            <li key={m.organization_id}>
              <Link href={`/orgs/${m.organization_id}`} className={styles.orgLink}>
                <span className={styles.orgName}>{m.organization_name}</span>
                <span className={styles.badge}>{roleLabel(m.role)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          You are not in any organization yet. Create one, or ask a colleague to invite you to
          theirs.
        </p>
      )}
      {user.email_verified ? (
        <p>
          <Link href="/orgs/new">Create an organization</Link>
        </p>
      ) : null}
    </section>
  );
}
