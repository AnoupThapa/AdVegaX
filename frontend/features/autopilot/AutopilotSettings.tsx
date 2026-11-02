"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { useAdAccounts, useAdCampaigns } from "@/features/advertising/api";
import styles from "@/features/advertising/advertising.module.css";
import own from "@/features/changes/changes.module.css";
import type { Organization } from "@/features/organizations/api";
import { canManageAutopilot, canRequestChanges } from "@/features/organizations/permissions";
import { addDays, todayIn } from "@/features/stores/dates";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useAutopilot,
  useAutopilotRuns,
  useEnableAutopilot,
  useSaveAutopilot,
  useStopAutopilot,
  type AutopilotPolicy,
  type AutopilotPolicyIn,
} from "./api";

export const MISSING: Record<string, string> = {
  installation_off: "Autopilot is switched off for this AdVegaX installation.",
  not_in_rollout: "This organization is not yet among those allowed to use autopilot.",
  too_few_verified_changes:
    "AdVegaX has not yet made enough changes from recommendations approved by a person.",
  mismatched_changes: "A change from a recommendation was not shown on the platform as sent.",
  changes_switched_off: "Changes to ad accounts are switched off or paused.",
  no_kinds: "Choose at least one kind of change.",
  no_ad_accounts: "Choose at least one ad account.",
};

export const STOPPED: Record<string, string> = {
  stopped: "Stopped by a person.",
  change_failed: "It stopped itself: an automatic change could not be made.",
  outcome_unknown: "It stopped itself: AdVegaX could not confirm an automatic change.",
  not_verified: "It stopped itself: the platform did not show a change as it was sent.",
  change_refused: "It stopped itself: an automatic change was refused before it was sent.",
  daily_limit_reached: "It stopped itself: it reached its daily limit twice within a week.",
};

const SKIPPED: Record<string, string> = {
  kind_not_allowed: "not a kind autopilot may make",
  no_change: "no change proposed",
  account_not_included: "ad account not included",
  campaign_excluded: "campaign excluded",
  campaign_too_new: "campaign too new",
  campaign_cooldown: "changed recently",
  not_a_decrease: "would not lower spend",
  decrease_too_large: "cut too large",
  cumulative_limit: "too much cut within the window",
  campaign_changed: "campaign changed",
  no_longer_true: "no longer true",
  closed: "no longer open",
};

const when = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      )
    : "—";

/** Settings → Autopilot (Phase 12): readiness, what it may do, where, its limits, on/off. */
export function AutopilotSettings({ org }: { org: Organization }) {
  const policy = useAutopilot(org.id);
  const [saved, setSaved] = useState(false);
  if (policy.error) return <Alert tone="error">{messageFor(policy.error)}</Alert>;
  if (!policy.data) return <p role="status">Loading…</p>;
  return (
    <section aria-labelledby="autopilot-settings" className={styles.section}>
      <h2 id="autopilot-settings">Autopilot</h2>
      <p className={styles.muted}>
        Autopilot may act on its own on two kinds of advice that only lower spend: pausing a
        campaign that spent without results, and lowering the daily budget of a campaign losing
        money. It never raises spend. Every change goes through Changes, is emailed to the owners
        and can be undone.
      </p>
      <State org={org} p={policy.data} />
      <PolicyForm
        key={policy.data.updated_at ?? "new"}
        org={org}
        p={policy.data}
        saved={saved}
        setSaved={setSaved}
      />
      <Enable org={org} p={policy.data} />
      <Runs org={org} />
    </section>
  );
}

function State({ org, p }: { org: Organization; p: AutopilotPolicy }) {
  const stop = useStopAutopilot(org.id);
  return (
    <div className={styles.panel}>
      {p.enabled ? (
        <Alert tone="info">
          Autopilot is on since {when(p.enabled_at)}. It acts after each daily look.
        </Alert>
      ) : (
        <p>
          <strong>Autopilot is off.</strong>
          {p.stopped_reason ? ` ${STOPPED[p.stopped_reason] ?? p.stopped_reason}` : ""}
          {p.stopped_at ? ` (${when(p.stopped_at)})` : ""}
        </p>
      )}
      {p.enabled && canRequestChanges(org.role) ? (
        <div className={own.actions}>
          <Button variant="danger" busy={stop.isPending} onClick={() => stop.mutate()}>
            Stop autopilot
          </Button>
        </div>
      ) : null}
      {stop.error ? <Alert tone="error">{messageFor(stop.error)}</Alert> : null}
      <h3>Ready to be switched on?</h3>
      {p.readiness.ready ? (
        <p>Yes.</p>
      ) : (
        <ul aria-label="Not ready yet">
          {p.readiness.missing.map((m) => (
            <li key={m}>{MISSING[m] ?? m}</li>
          ))}
        </ul>
      )}
      <p className={styles.muted}>
        Verified changes from approved recommendations: {p.readiness.verified_changes} of{" "}
        {p.readiness.needed_changes} needed.
      </p>
    </div>
  );
}

function AccountCampaigns({
  orgId,
  accountId,
  excluded,
  toggle,
  readOnly,
}: {
  orgId: string;
  accountId: string;
  excluded: string[];
  toggle: (id: string) => void;
  readOnly: boolean;
}) {
  const to = todayIn("UTC");
  const campaigns = useAdCampaigns(orgId, accountId, addDays(to, -6), to);
  const items = campaigns.data?.items ?? [];
  if (!items.length) return null;
  return (
    <fieldset className={own.form}>
      <legend>Exclude campaigns</legend>
      {items.map((c) => (
        <label key={c.id} className={own.choice}>
          <input
            type="checkbox"
            checked={excluded.includes(c.id)}
            disabled={readOnly}
            onChange={() => toggle(c.id)}
          />
          {c.name}
        </label>
      ))}
    </fieldset>
  );
}

const LIMIT_FIELDS = [
  ["max_changes_per_day", "Automatic changes per day, at most"],
  ["campaign_cooldown_days", "Days between automatic changes of one campaign, at least"],
  ["max_decrease_percent", "Budget cut per change (%), at most"],
  ["max_cumulative_decrease_percent", "Total budget cut within the window (%), at most"],
  ["cumulative_window_days", "That window (days)"],
  ["min_campaign_age_days", "Days a campaign has run, at least"],
] as const;

type LimitName = (typeof LIMIT_FIELDS)[number][0];

function PolicyForm({
  org,
  p,
  saved,
  setSaved,
}: {
  org: Organization;
  p: AutopilotPolicy;
  saved: boolean;
  setSaved: (value: boolean) => void;
}) {
  const save = useSaveAutopilot(org.id);
  const accounts = useAdAccounts(org.id);
  const manage = canManageAutopilot(org.role);
  const [kinds, setKinds] = useState<string[]>(p.kinds);
  const [included, setIncluded] = useState<string[]>(p.ad_account_ids);
  const [excluded, setExcluded] = useState<string[]>(p.excluded_campaign_ids);
  const [limits, setLimits] = useState<Record<LimitName, string>>(
    Object.fromEntries(LIMIT_FIELDS.map(([k]) => [k, String(p[k])])) as Record<LimitName, string>,
  );
  const flip = (list: string[], set: (v: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    save.mutate(
      {
        kinds: kinds as AutopilotPolicyIn["kinds"],
        ad_account_ids: included,
        excluded_campaign_ids: excluded,
        ...(Object.fromEntries(LIMIT_FIELDS.map(([k]) => [k, Number(limits[k])])) as Record<
          LimitName,
          number
        >),
      },
      { onSuccess: () => setSaved(true) },
    );
  };
  const linked = (accounts.data ?? []).filter((a) => a.linked);
  return (
    <form className={own.form} onSubmit={submit} noValidate aria-label="Autopilot policy">
      <fieldset className={own.form}>
        <legend>What it may do</legend>
        {[
          { value: "spend_without_results", label: "Pause a campaign that spent without results" },
          { value: "losing_money", label: "Lower the daily budget of a campaign losing money" },
        ].map(({ value, label }) => (
          <label key={value} className={own.choice}>
            <input
              type="checkbox"
              checked={kinds.includes(value)}
              disabled={!manage}
              onChange={() => flip(kinds, setKinds, value)}
            />
            {label}
          </label>
        ))}
      </fieldset>
      <fieldset className={own.form}>
        <legend>Ad accounts it may change</legend>
        {linked.length === 0 ? <p className={styles.muted}>No ad accounts linked yet.</p> : null}
        {linked.map((a) => (
          <label key={a.id} className={own.choice}>
            <input
              type="checkbox"
              checked={included.includes(a.id)}
              disabled={!manage}
              onChange={() => flip(included, setIncluded, a.id)}
            />
            {a.name ?? a.external_account_id} ({a.provider === "meta_ads" ? "Meta" : "Google Ads"})
          </label>
        ))}
      </fieldset>
      {included.map((id) => (
        <AccountCampaigns
          key={id}
          orgId={org.id}
          accountId={id}
          excluded={excluded}
          toggle={(c) => flip(excluded, setExcluded, c)}
          readOnly={!manage}
        />
      ))}
      <fieldset className={own.form}>
        <legend>Limits</legend>
        <p className={styles.muted}>
          This installation allows at most {p.ceilings.max_changes_per_day} changes a day, cuts of{" "}
          {p.ceilings.max_decrease_percent}% at a time and{" "}
          {p.ceilings.max_cumulative_decrease_percent}% within {p.ceilings.cumulative_window_days}{" "}
          days, at least {p.ceilings.campaign_cooldown_days} days between changes of a campaign and
          campaigns running for {p.ceilings.min_campaign_age_days} days. You can only make these
          stricter.
        </p>
        {LIMIT_FIELDS.map(([name, label]) => (
          <TextField
            key={name}
            label={label}
            inputMode="numeric"
            value={limits[name]}
            readOnly={!manage}
            onChange={(e) => setLimits({ ...limits, [name]: e.target.value })}
          />
        ))}
      </fieldset>
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
        <p className={styles.muted}>Only owners can change autopilot.</p>
      )}
    </form>
  );
}

function Enable({ org, p }: { org: Organization; p: AutopilotPolicy }) {
  const enable = useEnableAutopilot(org.id);
  const [confirm, setConfirm] = useState("");
  if (p.enabled || !canManageAutopilot(org.role)) return null;
  const details = enable.error instanceof ApiError ? enable.error.details : [];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    enable.mutate(confirm);
  };
  return (
    <form className={own.form} onSubmit={submit} noValidate aria-label="Switch autopilot on">
      <TextField
        label={`Type the organization's name (${org.name}) to switch autopilot on`}
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
      />
      {enable.error ? (
        <Alert tone="error">
          {messageFor(enable.error)}
          {details.length ? (
            <ul>
              {details.map((d, i) => (
                <li key={i}>{MISSING[d.reason ?? ""] ?? d.reason}</li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}
      <div className={own.actions}>
        <Button type="submit" busy={enable.isPending} disabled={!p.readiness.ready || !confirm}>
          Switch autopilot on
        </Button>
      </div>
    </form>
  );
}

function Runs({ org }: { org: Organization }) {
  const runs = useAutopilotRuns(org.id);
  const items = runs.data ?? [];
  if (!items.length) return null;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>Recent autopilot runs</caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Changes made</th>
            <th scope="col">Left to a person</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <th scope="row">{when(r.started_at)}</th>
              <td>
                {r.made.length}
                {r.stopped_reason ? ` — ${STOPPED[r.stopped_reason] ?? r.stopped_reason}` : ""}
              </td>
              <td>
                {r.skipped.length
                  ? r.skipped.map((s) => SKIPPED[String(s.reason)] ?? String(s.reason)).join(", ")
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** On the Overview: whether autopilot is on. */
export function OverviewAutopilot({ org }: { org: Organization }) {
  const policy = useAutopilot(org.id);
  if (!policy.data?.enabled) return null;
  return (
    <Alert tone="info">
      Autopilot is on: AdVegaX may pause campaigns or lower budgets on its own, within the limits an
      owner set. Settings → Autopilot.
    </Alert>
  );
}
