"use client";

import { PageHeading } from "@/components/ui/PageHeading";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { useSession } from "@/features/auth/session";

import styles from "./account.module.css";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { SessionsSection } from "./SessionsSection";

function Security() {
  const { user } = useSession();
  if (!user) return null;
  return (
    <div className={styles.page}>
      <PageHeading id="security-title">Account security</PageHeading>
      <p className={styles.muted}>
        Signed in as <strong>{user.email}</strong>.
      </p>
      <SessionsSection />
      <ChangePasswordForm email={user.email} />
    </div>
  );
}

export function AccountSecurityPage() {
  return (
    <RequireAuth>
      <Security />
    </RequireAuth>
  );
}
