"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import { TextField } from "@/components/ui/TextField";
import styles from "@/components/ui/ui.module.css";

import { useForgotPassword } from "./actions";
import { formFeedback } from "./form-errors";
import { emailErrors } from "./validation";

export function ForgotPasswordForm() {
  const forgot = useForgotPassword();
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [problem, setProblem] = useState<{ message: string; requestId: string | null } | null>(
    null,
  );
  const emailRef = useRef<HTMLInputElement>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = emailErrors(email);
    setProblem(null);
    setErrors(found);
    if (found.length) {
      emailRef.current?.focus();
      return;
    }
    forgot.mutate(email.trim(), {
      onError: (error) => {
        const feedback = formFeedback(error);
        setErrors(feedback.fields.email ?? []);
        setProblem({ message: feedback.message, requestId: feedback.requestId });
      },
    });
  }

  return (
    <PageCard title="Reset your password" footer={<Link href="/sign-in">Back to sign in</Link>}>
      {forgot.isSuccess ? (
        // Same message whether or not the address has an account (no account enumeration).
        <Alert tone="success">
          If an account exists for that address, we&apos;ve sent a link to reset the password. The
          link can be used once.
        </Alert>
      ) : (
        <>
          {problem ? (
            <Alert tone="error" requestId={problem.requestId}>
              {problem.message}
            </Alert>
          ) : null}
          <p>Enter your email and we&apos;ll send you a link to choose a new password.</p>
          <form onSubmit={onSubmit} noValidate aria-label="Reset your password">
            <TextField
              ref={emailRef}
              label="Email"
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              errors={errors}
            />
            <div className={styles.actions}>
              <Button type="submit" busy={forgot.isPending}>
                {forgot.isPending ? "Sending…" : "Send reset link"}
              </Button>
            </div>
          </form>
        </>
      )}
    </PageCard>
  );
}
