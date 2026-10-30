"use client";

import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { formFeedback } from "@/features/auth/form-errors";
import {
  PASSWORD_MIN_LENGTH,
  hasErrors,
  newPasswordErrors,
  type FieldErrors,
} from "@/features/auth/validation";
import { ApiError } from "@/lib/api/errors";

import styles from "./account.module.css";
import { useChangePassword } from "./queries";

export function ChangePasswordForm({ email }: { email: string }) {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fields, setFields] = useState<FieldErrors>({});
  const [notice, setNotice] = useState<{
    tone: "success" | "error";
    text: string;
    requestId: string | null;
  } | null>(null);
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  function focusFirst(found: FieldErrors) {
    if (found.current_password?.length) currentRef.current?.focus();
    else if (found.new_password?.length) nextRef.current?.focus();
    else if (found.confirm?.length) confirmRef.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: FieldErrors = {
      current_password: current ? [] : ["Enter your current password."],
      new_password: [
        ...newPasswordErrors(next, email),
        ...(next && next === current ? ["Choose a password different from your current one."] : []),
      ],
      confirm: confirm === next ? [] : ["The passwords do not match."],
    };
    setNotice(null);
    setFields(found);
    if (hasErrors(found)) {
      focusFirst(found);
      return;
    }
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          setNotice({
            tone: "success",
            text: "Your password has been changed. You have been signed out on your other devices.",
            requestId: null,
          });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "INVALID_CREDENTIALS") {
            const wrong = { current_password: ["Your current password is incorrect."] };
            setFields(wrong);
            setNotice({
              tone: "error",
              text: "Your current password is incorrect.",
              requestId: error.requestId,
            });
            focusFirst(wrong);
            return;
          }
          // The API reports password-policy problems on a field it calls "password".
          const feedback = formFeedback(error, { password: "new_password" });
          setFields(feedback.fields);
          setNotice({ tone: "error", text: feedback.message, requestId: feedback.requestId });
          focusFirst(feedback.fields);
        },
      },
    );
  }

  return (
    <section aria-labelledby="password-title" className={styles.section}>
      <h2 id="password-title">Change password</h2>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      <form
        onSubmit={onSubmit}
        noValidate
        aria-labelledby="password-title"
        className={styles.panel}
      >
        {/* Lets password managers attach the change to the right account. */}
        <input type="text" name="username" autoComplete="username" value={email} readOnly hidden />
        <TextField
          ref={currentRef}
          label="Current password"
          type="password"
          name="current_password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          errors={fields.current_password ?? []}
        />
        <TextField
          ref={nextRef}
          label="New password"
          type="password"
          name="new_password"
          autoComplete="new-password"
          required
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          value={next}
          onChange={(e) => setNext(e.target.value)}
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
        <Button type="submit" busy={change.isPending}>
          {change.isPending ? "Saving…" : "Change password"}
        </Button>
      </form>
    </section>
  );
}
