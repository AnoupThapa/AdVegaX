"use client";

import { Alert } from "@/components/ui/Alert";

import { ResendVerification } from "./ResendVerification";
import type { SessionUser } from "./session";

/** Unverified accounts can sign in but cannot create or join organizations (A15). */
export function UnverifiedNotice({ user }: { user: SessionUser }) {
  if (user.email_verified) return null;
  return (
    <section aria-labelledby="verify-title">
      <Alert tone="info">
        <h2 id="verify-title">Verify your email address</h2>
        <p>
          We sent a link to <strong>{user.email}</strong>. You need to verify your email before you
          can create or join an organization.
        </p>
      </Alert>
      <ResendVerification />
    </section>
  );
}
