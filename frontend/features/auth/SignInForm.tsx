"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import { TextField } from "@/components/ui/TextField";
import styles from "@/components/ui/ui.module.css";
import { safeNextPath } from "@/lib/navigation/safe-next";

import { useSignIn } from "./actions";
import { formFeedback } from "./form-errors";
import { useSession } from "./session";
import { emailErrors, hasErrors, type FieldErrors } from "./validation";

export function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNextPath(params.get("next"), "/");
  const { user } = useSession();
  const signIn = useSignIn();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<{ message: string; requestId: string | null } | null>(
    null,
  );
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  // Already signed in (or just signed in): go where the person was heading.
  useEffect(() => {
    if (user) router.replace(next);
  }, [user, next, router]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: FieldErrors = {
      email: emailErrors(email),
      password: password ? [] : ["Enter your password."],
    };
    setProblem(null);
    setFields(found);
    if (hasErrors(found)) {
      (found.email?.length ? emailRef : passwordRef).current?.focus();
      return;
    }
    signIn.mutate(
      { email: email.trim(), password },
      {
        onError: (error) => {
          const feedback = formFeedback(error);
          setFields(feedback.fields);
          setProblem({ message: feedback.message, requestId: feedback.requestId });
        },
      },
    );
  }

  return (
    <PageCard
      title="Sign in"
      footer={
        <p>
          New to AdVegaX? <Link href="/sign-up">Create an account</Link>
        </p>
      }
    >
      {problem ? (
        <Alert tone="error" requestId={problem.requestId}>
          {problem.message}
        </Alert>
      ) : null}
      <form onSubmit={onSubmit} noValidate aria-label="Sign in">
        <TextField
          ref={emailRef}
          label="Email"
          type="email"
          name="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          errors={fields.email ?? []}
        />
        <TextField
          ref={passwordRef}
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          errors={fields.password ?? []}
        />
        <div className={styles.actions}>
          <Button type="submit" busy={signIn.isPending}>
            {signIn.isPending ? "Signing in…" : "Sign in"}
          </Button>
          <Link href="/forgot-password">Forgot your password?</Link>
        </div>
      </form>
    </PageCard>
  );
}
