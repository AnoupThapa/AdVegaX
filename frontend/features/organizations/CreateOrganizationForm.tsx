"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import styles from "@/components/ui/ui.module.css";
import { formFeedback } from "@/features/auth/form-errors";
import { useSession } from "@/features/auth/session";
import { UnverifiedNotice } from "@/features/auth/UnverifiedNotice";
import { hasErrors, type FieldErrors } from "@/features/auth/validation";

import { useCreateOrganization } from "./api";
import {
  ORGANIZATION_FIELD_ALIASES,
  OrganizationFields,
  focusFirstError,
  validateOrganization,
  type OrganizationValues,
} from "./OrganizationFields";
import { browserTimeZone } from "./options";

/** Shown inside RequireAuth, so a signed-in user is present. */
export function CreateOrganizationForm() {
  const { user } = useSession();
  const router = useRouter();
  const create = useCreateOrganization();
  const [values, setValues] = useState<OrganizationValues>(() => ({
    name: "",
    currency: "",
    timeZone: browserTimeZone(),
  }));
  const [fields, setFields] = useState<FieldErrors>({});
  const [problem, setProblem] = useState<{ message: string; requestId: string | null } | null>(
    null,
  );
  const refs = {
    name: useRef<HTMLInputElement>(null),
    currency: useRef<HTMLSelectElement>(null),
    timeZone: useRef<HTMLSelectElement>(null),
  };

  if (user && !user.email_verified) {
    return (
      <PageCard title="Create an organization">
        <UnverifiedNotice user={user} />
      </PageCard>
    );
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateOrganization(values);
    setProblem(null);
    setFields(found);
    if (hasErrors(found)) {
      focusFirstError(found, refs);
      return;
    }
    create.mutate(
      {
        name: values.name.trim(),
        default_currency: values.currency,
        default_timezone: values.timeZone,
      },
      {
        onSuccess: (org) => router.push(`/orgs/${org.id}`),
        onError: (error) => {
          const feedback = formFeedback(error, ORGANIZATION_FIELD_ALIASES);
          setFields(feedback.fields);
          setProblem({ message: feedback.message, requestId: feedback.requestId });
          focusFirstError(feedback.fields, refs);
        },
      },
    );
  }

  return (
    <PageCard
      title="Create an organization"
      footer={
        <p>
          <Link href="/">Cancel</Link>
        </p>
      }
    >
      <p>An organization holds your stores, ad accounts and team. You will be its owner.</p>
      {problem ? (
        <Alert tone="error" requestId={problem.requestId}>
          {problem.message}
        </Alert>
      ) : null}
      <form onSubmit={onSubmit} noValidate aria-label="Create an organization">
        <OrganizationFields values={values} onChange={setValues} errors={fields} refs={refs} />
        <div className={styles.actions}>
          <Button type="submit" busy={create.isPending}>
            {create.isPending ? "Creating…" : "Create organization"}
          </Button>
        </div>
      </form>
    </PageCard>
  );
}
