"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { createContext, useContext, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useOrganization, type Organization } from "./api";
import { isOrganizationId } from "./options";
import styles from "./organizations.module.css";

const OrganizationContext = createContext<Organization | null>(null);

/** The organization of the current page, loaded by OrganizationShell. */
export function useCurrentOrganization(): Organization {
  const org = useContext(OrganizationContext);
  if (!org) throw new Error("useCurrentOrganization must be used inside OrganizationShell");
  return org;
}

/** Layout for /orgs/[organizationId]/…: signed-in users only. */
export function OrganizationShell({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <LoadedOrganization>{children}</LoadedOrganization>
    </RequireAuth>
  );
}

function LoadedOrganization({ children }: { children: ReactNode }) {
  const params = useParams<{ organizationId: string }>();
  const id = params.organizationId ?? "";
  // Malformed IDs are never sent to the API; they get the same "not found" as anyone else's.
  if (!isOrganizationId(id)) return <OrganizationNotFound />;
  return <FetchedOrganization id={id}>{children}</FetchedOrganization>;
}

function FetchedOrganization({ id, children }: { id: string; children: ReactNode }) {
  const query = useOrganization(id);
  if (query.data) {
    return (
      <OrganizationContext.Provider value={query.data}>
        <div className={styles.shell}>
          <OrganizationNav org={query.data} />
          <div className={styles.content}>{children}</div>
        </div>
      </OrganizationContext.Provider>
    );
  }
  if (query.error) {
    // The API answers 404 for organizations the user does not belong to (tenant isolation).
    if (query.error instanceof ApiError && query.error.status === 404) {
      return <OrganizationNotFound />;
    }
    return (
      <div className={styles.page}>
        <Alert
          tone="error"
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
        >
          {messageFor(query.error)}
        </Alert>
      </div>
    );
  }
  return (
    <p role="status" className={styles.page}>
      Loading…
    </p>
  );
}

/** Same wording whether the organization does not exist or belongs to someone else. */
export function OrganizationNotFound() {
  return (
    <section className={styles.page} aria-labelledby="org-not-found">
      <PageHeading id="org-not-found">Page not found</PageHeading>
      <p>This page does not exist, or you do not have access to it.</p>
      <p>
        <Link href="/">Go to the home page</Link>
      </p>
    </section>
  );
}

const SECTIONS = [
  { href: "", label: "Overview" },
  { href: "/members", label: "Members" },
  { href: "/settings", label: "Settings" },
] as const;

function OrganizationNav({ org }: { org: Organization }) {
  const pathname = usePathname();
  const base = `/orgs/${org.id}`;
  return (
    <nav aria-label="Organization" className={styles.nav}>
      <p className={styles.navTitle}>{org.name}</p>
      <ul className={styles.navList}>
        {SECTIONS.map((section) => {
          const href = `${base}${section.href}`;
          const current = pathname === href;
          return (
            <li key={section.label}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={current ? styles.navCurrent : styles.navLink}
              >
                {section.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
