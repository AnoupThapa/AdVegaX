"use client";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { messageFor } from "@/lib/api/errors";

import { useResendVerification } from "./actions";

export function ResendVerification() {
  const resend = useResendVerification();
  return (
    <div>
      {resend.isSuccess ? (
        <Alert tone="success">We&apos;ve sent a new verification link to your email.</Alert>
      ) : null}
      {resend.isError ? <Alert tone="error">{messageFor(resend.error)}</Alert> : null}
      <Button variant="secondary" busy={resend.isPending} onClick={() => resend.mutate()}>
        {resend.isPending ? "Sending…" : "Send a new verification link"}
      </Button>
    </div>
  );
}
