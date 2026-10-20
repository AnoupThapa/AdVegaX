"use client";

import { useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import ui from "@/components/ui/ui.module.css";
import { formFeedback } from "@/features/auth/form-errors";
import { hasErrors, type FieldErrors } from "@/features/auth/validation";
import { StoreAssignments } from "@/features/overview/StoreAssignments";

import { useUpdateOrganization, type Organization, type OrganizationUpdate } from "./api";
import {
  ORGANIZATION_FIELD_ALIASES,
  OrganizationFields,
  focusFirstError,
  validateOrganization,
  type OrganizationValues,
} from "./OrganizationFields";
import { useCurrentOrganization } from "./OrganizationShell";
import styles from "./organizations.module.css";
import { canUpdateOrganization, roleLabel } from "./permissions";

export function OrganizationSettings() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="settings-title">
      <PageHeading id="settings-title">Settings</PageHeading>
      {canUpdateOrganization(org.role) ? (
        <SettingsForm org={org} />
      ) : (
        <ReadOnlySettings org={org} />
      )}
      <StoreAssignments org={org} />
    </section>
  );
}

function ReadOnlySettings({ org }: { org: Organization }) {
  return (
    <div className={styles.panel}>
      <dl className={styles.details}>
        <dt>Name</dt>
        <dd>{org.name}</dd>
        <dt>Reporting currency</dt>
        <dd>{org.default_currency}</dd>
        <dt>Time zone</dt>
        <dd>{org.default_timezone.replaceAll("_", " ")}</dd>
      </dl>
      <p className={styles.muted}>
        Only owners and admins can change these settings. Your role is {roleLabel(org.role)}.
      </p>
    </div>
  );
}

function SettingsForm({ org }: { org: Organization }) {
  const update = useUpdateOrganization(org.id);
  const saved: OrganizationValues = {
    name: org.name,
    currency: org.default_currency,
    timeZone: org.default_timezone,
  };
  const [values, setValues] = useState<OrganizationValues>(saved);
  const [fields, setFields] = useState<FieldErrors>({});
  const [notice, setNotice] = useState<{
    tone: "error" | "success";
    message: string;
    requestId: string | null;
  } | null>(null);
  const refs = {
    name: useRef<HTMLInputElement>(null),
    currency: useRef<HTMLSelectElement>(null),
    timeZone: useRef<HTMLSelectElement>(null),
  };

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validateOrganization(values);
    setNotice(null);
    setFields(found);
    if (hasErrors(found)) {
      focusFirstError(found, refs);
      return;
    }
    // Send only what changed.
    const body: OrganizationUpdate = {};
    if (values.name.trim() !== org.name) body.name = values.name.trim();
    if (values.currency !== org.default_currency) body.default_currency = values.currency;
    if (values.timeZone !== org.default_timezone) body.default_timezone = values.timeZone;
    if (Object.keys(body).length === 0) {
      setNotice({ tone: "success", message: "No changes to save.", requestId: null });
      return;
    }
    update.mutate(body, {
      onSuccess: () => setNotice({ tone: "success", message: "Settings saved.", requestId: null }),
      onError: (error) => {
        const feedback = formFeedback(error, ORGANIZATION_FIELD_ALIASES);
        setFields(feedback.fields);
        setNotice({ tone: "error", message: feedback.message, requestId: feedback.requestId });
        focusFirstError(feedback.fields, refs);
      },
    });
  }

  return (
    <div className={styles.panel}>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.message}
        </Alert>
      ) : null}
      <form onSubmit={onSubmit} noValidate aria-label="Organization settings">
        <OrganizationFields
          values={values}
          onChange={setValues}
          errors={fields}
          refs={refs}
          saved={{ currency: org.default_currency, timeZone: org.default_timezone }}
        />
        <div className={ui.actions}>
          <Button type="submit" busy={update.isPending}>
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </div>
  );
}
