"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import { TextField } from "@/components/ui/TextField";
import styles from "@/components/ui/ui.module.css";

import { useSignUp } from "./actions";
import { formFeedback } from "./form-errors";
import {
  PASSWORD_MIN_LENGTH,
  emailErrors,
  hasErrors,
  newPasswordErrors,
  type FieldErrors,
} from "./validation";

export function SignUpForm() {
  const router = useRouter();
  const signUp = useSignUp();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<{ message: string; requestId: string | null } | null>(
    null,
  );
  const nameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  function focusFirst(found: FieldErrors) {
    if (found.display_name?.length) nameRef.current?.focus();
    else if (found.email?.length) emailRef.current?.focus();
    else if (found.password?.length) passwordRef.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found: FieldErrors = {
      display_name: name.trim().length > 120 ? ["Use at most 120 characters."] : [],
      email: emailErrors(email),
      password: newPasswordErrors(password, email),
    };
    setProblem(null);
    setFields(found);
    if (hasErrors(found)) {
      focusFirst(found);
      return;
    }
    signUp.mutate(
      { email: email.trim(), password, display_name: name.trim() || null },
      {
        // The API answers the same way whether or not the address already has an account.
        onSuccess: () => router.push("/check-email"),
        onError: (error) => {
          const feedback = formFeedback(error);
          setFields(feedback.fields);
          setProblem({ message: feedback.message, requestId: feedback.requestId });
          focusFirst(feedback.fields);
        },
      },
    );
  }

  return (
    <PageCard
      title="Create your account"
      footer={
        <p>
          Already have an account? <Link href="/sign-in">Sign in</Link>
        </p>
      }
    >
      {problem ? (
        <Alert tone="error" requestId={problem.requestId}>
          {problem.message}
        </Alert>
      ) : null}
      <form onSubmit={onSubmit} noValidate aria-label="Create your account">
        <TextField
          ref={nameRef}
          label="Your name"
          name="display_name"
          autoComplete="name"
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
          errors={fields.display_name ?? []}
        />
        <TextField
          ref={emailRef}
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
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
          autoComplete="new-password"
          required
          hint={`At least ${PASSWORD_MIN_LENGTH} characters. A short phrase is easiest to remember.`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          errors={fields.password ?? []}
        />
        <div className={styles.actions}>
          <Button type="submit" busy={signUp.isPending}>
            {signUp.isPending ? "Creating account…" : "Create account"}
          </Button>
        </div>
      </form>
    </PageCard>
  );
}
