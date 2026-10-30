"use client";

import type { ReactNode } from "react";

import { OrganizationList } from "@/features/organizations/OrganizationList";
import { useSession } from "@/features/auth/session";
import { UnverifiedNotice } from "@/features/auth/UnverifiedNotice";

import styles from "./landing.module.css";

/**
 * Signed-out visitors (and the first paint, which cannot know yet) get the public page; signed-in
 * users get their organizations. The public page is rendered on the server so it can be indexed.
 */
export function HomeGate({ landing }: { landing: ReactNode }) {
  const { user } = useSession();
  if (!user) return <>{landing}</>;
  return (
    <section aria-labelledby="home-title" className={styles.signedIn}>
      <h1 id="home-title">{`Welcome back, ${user.display_name || user.email}`}</h1>
      <UnverifiedNotice user={user} />
      <OrganizationList user={user} />
    </section>
  );
}
