"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageCard } from "@/components/ui/PageCard";
import { messageFor } from "@/lib/api/errors";

import { useVerifyEmail } from "./actions";
import { useFragmentToken } from "./fragment-token";
import { ResendVerification } from "./ResendVerification";
import { useSession } from "./session";

export function VerifyEmail() {
  const token = useFragmentToken();
  const verify = useVerifyEmail();
  const { user } = useSession();
  const sent = useRef(false);

  useEffect(() => {
    // Tokens are single-use: send exactly once, even if React runs effects twice.
    if (token && !sent.current) {
      sent.current = true;
      verify.mutate(token);
    }
  }, [token, verify]);

  let body;
  if (token === null) {
    body = (
      <Alert tone="error">
        This verification link is incomplete. Open the link from your email again.
      </Alert>
    );
  } else if (verify.isSuccess) {
    body = (
      <>
        <Alert tone="success">Your email address is verified.</Alert>
        <p>{user ? <Link href="/">Continue</Link> : <Link href="/sign-in">Sign in</Link>}</p>
      </>
    );
  } else if (verify.isError) {
    body = (
      <>
        <Alert tone="error">{messageFor(verify.error)}</Alert>
        {user ? (
          <ResendVerification />
        ) : (
          <p>
            <Link href="/sign-in">Sign in</Link> to request a new link.
          </p>
        )}
      </>
    );
  } else {
    body = <p role="status">Checking your link…</p>;
  }

  return <PageCard title="Verify your email">{body}</PageCard>;
}
