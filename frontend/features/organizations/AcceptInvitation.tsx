"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import ui from "@/components/ui/ui.module.css";
import { useSignOut } from "@/features/auth/actions";
import { useFragmentToken } from "@/features/auth/fragment-token";
import { useSession } from "@/features/auth/session";
import { UnverifiedNotice } from "@/features/auth/UnverifiedNotice";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useAcceptInvitation } from "./api";
import {
  forgetInvitationToken,
  pendingInvitationToken,
  rememberInvitationToken,
} from "./invitation-token";

const HERE = "/invitations/accept";
const SIGN_IN = `/sign-in?next=${encodeURIComponent(HERE)}`;

/** Errors after which the same link can never work, so the token is dropped. */
const FINAL_ERRORS = new Set(["INVALID_TOKEN", "INVITATION_NOT_PENDING", "NOT_FOUND"]);

export function AcceptInvitation() {
  const fragmentToken = useFragmentToken({ followHashChanges: true });
  // A token in the link wins; otherwise use the one remembered before a sign-in detour.
  const token =
    fragmentToken === undefined ? undefined : (fragmentToken ?? pendingInvitationToken());

  useEffect(() => {
    if (fragmentToken) rememberInvitationToken(fragmentToken);
  }, [fragmentToken]);

  // A different link starts afresh (no error left over from the previous one).
  return <AcceptInvitationBody key={token ?? String(token)} token={token} />;
}

function AcceptInvitationBody({ token }: { token: string | null | undefined }) {
  const { user } = useSession();
  const accept = useAcceptInvitation();
  const signOut = useSignOut();
  const router = useRouter();

  function onAccept() {
    if (!token) return;
    accept.mutate(token, {
      onSuccess: (org) => {
        forgetInvitationToken();
        router.push(`/orgs/${org.id}`);
      },
      onError: (error) => {
        if (error instanceof ApiError && FINAL_ERRORS.has(error.code)) forgetInvitationToken();
      },
    });
  }

  let body;
  if (token === undefined || user === undefined) {
    body = <p role="status">Loading…</p>;
  } else if (token === null) {
    body = (
      <Alert tone="error">
        This invitation link is incomplete. Open the link from your invitation email again.
      </Alert>
    );
  } else if (user === null) {
    body = (
      <>
        <p>
          You have been invited to join an organization on AdVegaX. Sign in with the email address
          the invitation was sent to.
        </p>
        <div className={ui.actions}>
          <Link href={SIGN_IN}>Sign in to accept</Link>
          <Link href="/sign-up">Create an account</Link>
        </div>
        <p>
          New here? After creating your account and verifying your email, open the invitation link
          from your email again.
        </p>
      </>
    );
  } else if (!user.email_verified) {
    body = (
      <>
        <UnverifiedNotice user={user} />
        <p>After verifying your email, open the invitation link from your email again.</p>
      </>
    );
  } else {
    const error = accept.error;
    const mismatch = error instanceof ApiError && error.code === "INVITATION_EMAIL_MISMATCH";
    const final = error instanceof ApiError && FINAL_ERRORS.has(error.code);
    body = (
      <>
        {error ? (
          <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
            {messageFor(error)}
            {final ? " Ask the person who invited you to send a new invitation." : null}
          </Alert>
        ) : null}
        {final ? (
          <p>
            <Link href="/">Go to the home page</Link>
          </p>
        ) : (
          <>
            <p>
              You have been invited to join an organization on AdVegaX. You are signed in as{" "}
              <strong>{user.email}</strong>.
            </p>
            {mismatch ? (
              <p>Sign out, then sign in with the email address the invitation was sent to.</p>
            ) : null}
            <div className={ui.actions}>
              {mismatch ? null : (
                <Button busy={accept.isPending} onClick={onAccept}>
                  {accept.isPending ? "Accepting…" : "Accept invitation"}
                </Button>
              )}
              <Button
                variant={mismatch ? "primary" : "secondary"}
                busy={signOut.isPending}
                onClick={() => signOut.mutate(undefined, { onSettled: () => router.push(SIGN_IN) })}
              >
                {mismatch ? "Sign out and switch account" : "Not you? Sign out"}
              </Button>
            </div>
          </>
        )}
      </>
    );
  }

  return <PageCard title="Join an organization">{body}</PageCard>;
}
