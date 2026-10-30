"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { canManageChangeSettings } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import {
  useChangeSettings,
  useSaveChangeSettings,
  useSetWriteAccess,
  useWriteAccess,
  type ActionSettings,
} from "./api";
import own from "./changes.module.css";
import { reasonText } from "./labels";

/** Settings → Changes: pause all, the second-person rule and the maximum daily budget. */
export function ChangeSettings({ org }: { org: Organization }) {
  const settings = useChangeSettings(org.id);
  const [saved, setSaved] = useState(false);
  if (settings.error) return <Alert tone="error">{messageFor(settings.error)}</Alert>;
  if (!settings.data) return <p role="status">Loading…</p>;
  return (
    <SettingsForm
      key={settings.data.updated_at ?? "new"}
      org={org}
      settings={settings.data}
      saved={saved}
      setSaved={setSaved}
    />
  );
}

function SettingsForm({
  org,
  settings,
  saved,
  setSaved,
}: {
  org: Organization;
  settings: ActionSettings;
  saved: boolean;
  setSaved: (value: boolean) => void;
}) {
  const save = useSaveChangeSettings(org.id);
  const manage = canManageChangeSettings(org.role);
  const [paused, setPaused] = useState(settings.paused);
  const [second, setSecond] = useState(settings.require_second_person);
  const [maximum, setMaximum] = useState(settings.max_daily_budget ?? "");
  const [domains, setDomains] = useState((settings.landing_domains ?? []).join(", "));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    save.mutate(
      {
        paused,
        require_second_person: second,
        max_daily_budget: maximum.trim() ? maximum.trim() : null,
        landing_domains: domains
          .split(/[\s,]+/)
          .map((d) => d.trim())
          .filter(Boolean),
      },
      { onSuccess: () => setSaved(true) },
    );
  };
  return (
    <section aria-labelledby="change-settings" className={styles.section}>
      <h2 id="change-settings">Changes to ad accounts</h2>
      {!settings.engine_enabled ? (
        <Alert tone="info">
          Changes are switched off for this AdVegaX installation. Nothing can be requested or sent
          until they are switched on.
        </Alert>
      ) : null}
      <p className={styles.muted}>
        Limits for every change: a daily budget may go up at most {settings.increase_percent}% or
        down at most {settings.decrease_percent}% at a time, once every{" "}
        {settings.budget_change_interval_minutes} minutes per campaign, and at most{" "}
        {settings.daily_limit_per_account} changes per ad account a day.
      </p>
      <form className={own.form} onSubmit={submit} noValidate aria-label="Change settings">
        <label className={own.choice}>
          <input
            type="checkbox"
            checked={paused}
            disabled={!manage}
            onChange={(e) => setPaused(e.target.checked)}
          />
          Pause all changes (approved changes wait until this is lifted)
        </label>
        <label className={own.choice}>
          <input
            type="checkbox"
            checked={second}
            disabled={!manage}
            onChange={(e) => setSecond(e.target.checked)}
          />
          Require a second person: whoever asks for a change cannot approve it
        </label>
        <TextField
          label={`Maximum daily budget per campaign (${settings.currency})`}
          hint={
            settings.max_daily_budget
              ? `Now ${formatMoney(settings.max_daily_budget, settings.currency, settings.currency_minor_units)}. Budget changes above it are refused.`
              : "Not chosen yet: budget changes are refused until you choose one."
          }
          inputMode="decimal"
          value={maximum}
          readOnly={!manage}
          onChange={(e) => setMaximum(e.target.value)}
        />
        <TextField
          label="Your store's web addresses for landing pages"
          hint="For example evezone.com.au — needed when your store uses its own domain. Separate several with commas."
          value={domains}
          readOnly={!manage}
          onChange={(e) => setDomains(e.target.value)}
        />
        {save.error ? (
          <Alert
            tone="error"
            requestId={save.error instanceof ApiError ? save.error.requestId : null}
          >
            {messageFor(save.error)}
            {save.error instanceof ApiError && save.error.details.length
              ? ` ${save.error.details.map((d) => reasonText(d.reason ?? null)).join(" ")}`
              : ""}
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

/** On a connection's page: whether AdVegaX may change ad accounts through it. */
export function WriteAccessPanel({
  orgId,
  role,
  connectionId,
  active,
  onSignIn,
  signingIn,
}: {
  orgId: string;
  role: string;
  connectionId: string;
  active: boolean;
  onSignIn: () => void;
  signingIn: boolean;
}) {
  const access = useWriteAccess(orgId, connectionId, active);
  const change = useSetWriteAccess(orgId, connectionId);
  const manage = canManageChangeSettings(role);
  if (!active || !access.data || !access.data.supported) return null;
  const a = access.data;
  const needsPermission = a.missing_permissions.length > 0;
  return (
    <section aria-labelledby="write-access" className={styles.panel}>
      <h2 id="write-access">Changes through this connection</h2>
      {change.error ? (
        <Alert tone="error">
          {messageFor(change.error)}
          {change.error instanceof ApiError && change.error.details.length
            ? ` ${change.error.details.map((d) => reasonText(d.reason ?? null)).join(" ")}`
            : ""}
        </Alert>
      ) : null}
      <p>
        {a.allowed
          ? "Allowed: AdVegaX may pause, resume and change daily budgets of campaigns reached through this connection — each change approved by an owner or admin."
          : needsPermission
            ? "Read only. The platform has not given AdVegaX permission to make changes."
            : "Read only (the default). AdVegaX does not change anything through this connection."}
      </p>
      {manage ? (
        <div className={own.actions}>
          {needsPermission && a.can_request_permission ? (
            <Button variant="secondary" busy={signingIn} onClick={onSignIn}>
              Sign in again to allow changes
            </Button>
          ) : null}
          {!a.allowed && !needsPermission ? (
            <Button busy={change.isPending} onClick={() => change.mutate(true)}>
              Allow changes
            </Button>
          ) : null}
          {a.allowed ? (
            <Button
              variant="secondary"
              busy={change.isPending}
              onClick={() => change.mutate(false)}
            >
              Stop allowing changes
            </Button>
          ) : null}
        </div>
      ) : (
        <p className={styles.muted}>Owners and admins decide whether changes are allowed.</p>
      )}
    </section>
  );
}
