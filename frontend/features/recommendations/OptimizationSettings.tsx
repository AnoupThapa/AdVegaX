"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import own from "@/features/changes/changes.module.css";
import type { Organization } from "@/features/organizations/api";
import { canManageChangeSettings } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useOptimizationSettings,
  useSaveOptimizationSettings,
  type OptimizationSettings as Settings,
} from "./api";

/** Settings → Recommendations: the thresholds of the daily look (owners and admins). */
export function OptimizationSettings({ org }: { org: Organization }) {
  const settings = useOptimizationSettings(org.id);
  if (settings.error) return <Alert tone="error">{messageFor(settings.error)}</Alert>;
  if (!settings.data) return <p role="status">Loading…</p>;
  return <Form key={settings.data.updated_at ?? "new"} org={org} settings={settings.data} />;
}

function Form({ org, settings }: { org: Organization; settings: Settings }) {
  const save = useSaveOptimizationSettings(org.id);
  const manage = canManageChangeSettings(org.role);
  const [saved, setSaved] = useState(false);
  const [minSpend, setMinSpend] = useState(settings.min_spend);
  const [minConversions, setMinConversions] = useState(String(settings.min_conversions));
  const [step, setStep] = useState(String(settings.budget_step_percent));
  const [jump, setJump] = useState(String(settings.cost_jump_percent));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    save.mutate(
      {
        min_spend: minSpend.trim(),
        min_conversions: Number(minConversions),
        budget_step_percent: Number(step),
        cost_jump_percent: Number(jump),
      },
      { onSuccess: () => setSaved(true) },
    );
  };
  const field = (value: string, set: (v: string) => void) => ({
    value,
    readOnly: !manage,
    inputMode: "decimal" as const,
    onChange: (e: { target: { value: string } }) => set(e.target.value),
  });
  return (
    <section aria-labelledby="optimization-settings" className={styles.section}>
      <h2 id="optimization-settings">Recommendations</h2>
      {!settings.enabled ? (
        <Alert tone="info">Recommendations are switched off for this AdVegaX installation.</Alert>
      ) : null}
      <p className={styles.muted}>
        AdVegaX looks at running campaigns once a day and gives advice only when there is enough
        data.
      </p>
      <form className={own.form} onSubmit={submit} noValidate aria-label="Recommendation settings">
        <TextField
          label={`Least spend in the last 7 days to judge a campaign (${settings.currency})`}
          {...field(minSpend, setMinSpend)}
        />
        <TextField
          label="Least conversions in the 28 days before, for the profit and cost rules"
          {...field(minConversions, setMinConversions)}
        />
        <TextField
          label="Budget step (%)"
          hint={`How much a proposed budget goes up or down; at most ${settings.max_step_percent}%.`}
          {...field(step, setStep)}
        />
        <TextField
          label="Cost per conversion jump that is reported (%)"
          {...field(jump, setJump)}
        />
        {save.error ? (
          <Alert
            tone="error"
            requestId={save.error instanceof ApiError ? save.error.requestId : null}
          >
            {messageFor(save.error)}
          </Alert>
        ) : null}
        {saved ? <Alert tone="success">Saved.</Alert> : null}
        {manage ? (
          <div className={own.actions}>
            <Button type="submit" busy={save.isPending}>
              Save
            </Button>
          </div>
        ) : (
          <p className={styles.muted}>Only owners and admins can change these settings.</p>
        )}
      </form>
    </section>
  );
}
