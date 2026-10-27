"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canRequestChanges } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import {
  useActions,
  useRequestChange,
  useValidateChange,
  type ActionPreview,
  type ActionType,
} from "./api";
import { CheckList, Status, moneyOf } from "./ChangesPages";
import own from "./changes.module.css";
import { ACTION_LABELS, describe, reasonText } from "./labels";

type Campaign = {
  readonly id: string;
  readonly status: string;
  readonly provider: string;
  readonly currency: string;
  readonly currency_minor_units: number;
};

function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? error.details : [];
  return (
    <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
      {messageFor(error)}
      {details.length ? (
        <ul>
          {details.map((d, i) => (
            <li key={i}>{reasonText(d.reason ?? null)}</li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

/** On a campaign's page: pause, resume or change the daily budget — checked by AdVegaX and
 * tested by the platform first, then sent only after an owner or admin approves. */
export function CampaignChanges({ campaign }: { campaign: Campaign }) {
  const org = useCurrentOrganization();
  const recent = useActions(org.id, "", campaign.id);
  const validate = useValidateChange(org.id);
  const request = useRequestChange(org.id);
  const [kind, setKind] = useState<ActionType | null>(null);
  const [amount, setAmount] = useState("");
  const [preview, setPreview] = useState<ActionPreview | null>(null);
  const [made, setMade] = useState<string | null>(null);
  const money = (v: string | null | undefined) =>
    formatMoney(v, campaign.currency, campaign.currency_minor_units);
  const allowed = canRequestChanges(org.role);
  const open = recent.data?.find((a) =>
    ["pending", "approved", "queued", "submitting", "unknown"].includes(a.status),
  );

  const body = (type: ActionType) => ({
    action_type: type,
    campaign_id: campaign.id,
    params: type === "campaign.set_daily_budget" ? { daily_budget: amount.trim() } : {},
  });

  const choose = (type: ActionType) => {
    setKind(type);
    setPreview(null);
    setMade(null);
    validate.reset();
    request.reset();
    if (type !== "campaign.set_daily_budget")
      validate.mutate(body(type), { onSuccess: setPreview });
  };

  const check = (event: FormEvent) => {
    event.preventDefault();
    if (kind) validate.mutate(body(kind), { onSuccess: setPreview });
  };

  const send = () => {
    if (!kind) return;
    request.mutate(body(kind), {
      onSuccess: (action) => {
        setMade(action.id);
        setKind(null);
        setPreview(null);
      },
    });
  };

  return (
    <section aria-labelledby="campaign-changes" className={styles.section}>
      <h2 id="campaign-changes">Changes</h2>
      <p className={styles.muted}>
        Changes are checked by AdVegaX and tested by the platform first. Nothing is sent until an
        owner or admin approves it.
      </p>
      {made ? (
        <Alert tone="success">
          The change was requested and waits for approval.{" "}
          <Link href={`/orgs/${org.id}/changes/${made}`}>Open it</Link>
        </Alert>
      ) : null}
      {open ? (
        <Alert tone="info">
          A change of this campaign is in progress: {describe(open, moneyOf(open))} —{" "}
          <Status status={open.status} />.{" "}
          <Link href={`/orgs/${org.id}/changes/${open.id}`}>Open it</Link>
        </Alert>
      ) : null}
      {allowed && !open && campaign.status !== "removed" && campaign.status !== "archived" ? (
        <div className={own.actions}>
          {campaign.status === "active" ? (
            <Button variant="secondary" onClick={() => choose("campaign.pause")}>
              Pause
            </Button>
          ) : null}
          {campaign.status === "paused" ? (
            <Button variant="secondary" onClick={() => choose("campaign.resume")}>
              Resume
            </Button>
          ) : null}
          <Button variant="secondary" onClick={() => choose("campaign.set_daily_budget")}>
            Change budget
          </Button>
        </div>
      ) : null}
      {!allowed ? (
        <p className={styles.muted}>Owners, admins and managers can request changes.</p>
      ) : null}

      {kind ? (
        <div className={styles.panel}>
          <h3>{ACTION_LABELS[kind]}</h3>
          {kind === "campaign.set_daily_budget" ? (
            <form className={own.form} onSubmit={check} noValidate aria-label="Daily budget change">
              <TextField
                label={`New daily budget (${campaign.currency})`}
                inputMode="decimal"
                required
                value={amount}
                onChange={(e) => {
                  setAmount(e.target.value);
                  setPreview(null);
                }}
              />
              <div className={own.actions}>
                <Button type="submit" variant="secondary" busy={validate.isPending}>
                  Check
                </Button>
              </div>
            </form>
          ) : null}
          {validate.isPending && kind !== "campaign.set_daily_budget" ? (
            <p role="status">Checking…</p>
          ) : null}
          <ErrorNotice error={validate.error ?? request.error} />
          {preview ? (
            <>
              {preview.current ? (
                <p>
                  Now: {preview.current.status === "active" ? "running" : preview.current.status}
                  {preview.current.daily_budget
                    ? ` · ${money(preview.current.daily_budget)} a day`
                    : ""}
                </p>
              ) : null}
              {preview.budget_limits ? (
                <p className={styles.muted}>
                  One change may set between {money(preview.budget_limits.lowest)} and{" "}
                  {money(preview.budget_limits.highest)} a day (at most{" "}
                  {preview.budget_limits.increase_percent}% up or{" "}
                  {preview.budget_limits.decrease_percent}% down; platform minimum{" "}
                  {money(preview.budget_limits.platform_minimum)}, your maximum{" "}
                  {money(preview.budget_limits.organization_maximum)}).
                </p>
              ) : null}
              <CheckList checks={preview.checks} dryRun={preview.dry_run} />
              <div className={own.actions}>
                <Button busy={request.isPending} disabled={!preview.passed} onClick={send}>
                  Request this change
                </Button>
                <Button variant="secondary" onClick={() => setKind(null)}>
                  Cancel
                </Button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}

      {recent.data?.length ? (
        <ul className={own.history} aria-label="Recent changes of this campaign">
          {recent.data.slice(0, 5).map((a) => (
            <li key={a.id}>
              <Link href={`/orgs/${org.id}/changes/${a.id}`}>{describe(a, moneyOf(a))}</Link> —{" "}
              <Status status={a.status} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
