"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import { TextField } from "@/components/ui/TextField";
import styles from "@/components/ui/ui.module.css";
import { ApiError } from "@/lib/api/errors";

import { useResetPassword } from "./actions";
import { formFeedback } from "./form-errors";
import { useFragmentToken } from "./fragment-token";
import { PASSWORD_MIN_LENGTH, hasErrors, newPasswordErrors, type FieldErrors } from "./validation";

export function ResetPasswordForm() {
  const token = useFragmentToken();
  const reset = useResetPassword();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<{
    message: string;
    requestId: string | null;
    invalidLink: boolean;
  } | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const found: FieldErrors = {
      new_password: newPasswordErrors(password),
      confirm: confirm === password ? [] : ["The passwords do not match."],
    };
    setProblem(null);
    setFields(found);
    if (hasErrors(found)) {
      (found.new_password?.length ? passwordRef : confirmRef).current?.focus();
      return;
    }
    reset.mutate(
      { token, new_password: password },
      {
        onError: (error) => {
          // The API reports password-policy problems on the field it calls "password".
          const feedback = formFeedback(error, { password: "new_password" });
          setFields(feedback.fields);
          setProblem({
            message: feedback.message,
            requestId: feedback.requestId,
            invalidLink: error instanceof ApiError && error.code === "INVALID_TOKEN",
          });
        },
      },
    );
  }

  const requestNew = <Link href="/forgot-password">Request a new reset link</Link>;
  let body;
  if (token === undefined) {
    body = <p role="status">Checking your link…</p>;
  } else if (token === null) {
    body = (
      <>
        <Alert tone="error">
          This reset link is incomplete. Open the link from your email again.
        </Alert>
        <p>{requestNew}</p>
      </>
    );
  } else if (reset.isSuccess) {
    body = (
      <>
        <Alert tone="success">
          Your password has been changed. For your security, you have been signed out on every
          device.
        </Alert>
        <p>
          <Link href="/sign-in">Sign in with your new password</Link>
        </p>
      </>
    );
  } else {
    body = (
      <>
        {problem ? (
          <Alert tone="error" requestId={problem.requestId}>
            {problem.message} {problem.invalidLink ? requestNew : null}
          </Alert>
        ) : null}
        <form onSubmit={onSubmit} noValidate aria-label="Choose a new password">
          <TextField
            ref={passwordRef}
            label="New password"
            type="password"
            name="new_password"
            autoComplete="new-password"
            required
            hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            errors={fields.new_password ?? []}
          />
          <TextField
            ref={confirmRef}
            label="Confirm new password"
            type="password"
            name="confirm"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            errors={fields.confirm ?? []}
          />
          <div className={styles.actions}>
            <Button type="submit" busy={reset.isPending}>
              {reset.isPending ? "Saving…" : "Save new password"}
            </Button>
          </div>
        </form>
      </>
    );
  }

  return <PageCard title="Choose a new password">{body}</PageCard>;
}
