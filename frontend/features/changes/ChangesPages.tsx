"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canApproveChanges, canRequestChanges } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import {
  useAction,
  useActions,
  useApproveChange,
  useCancelChange,
  useRejectChange,
  useUndoChange,
  type Action,
  type ActionCheck,
} from "./api";
import { CHECK_GROUPS, VERIFICATION, describe, reasonText, statusLabel } from "./labels";
import own from "./changes.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FILTERS = [
  { value: "open", label: "Waiting or on their way" },
  { value: "succeeded", label: "Done" },
  { value: "failed", label: "Not made" },
  { value: "", label: "All changes" },
];
const when = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      )
    : "—";

export function moneyOf(action: Pick<Action, "currency" | "currency_minor_units">) {
  return (value: string) => formatMoney(value, action.currency, action.currency_minor_units);
}

export function Status({ status }: { status: string }) {
  const s = statusLabel(status);
  return <span className={`${styles.status} ${styles[s.tone]}`}>{s.label}</span>;
}

/** The checks in plain words: what failed and why, or that every check passed. */
export function CheckList({
  checks,
  dryRun,
}: {
  checks: readonly ActionCheck[];
  dryRun?: { result: string; reason?: string | null } | null;
}) {
  const failed = checks.filter((c) => c.result === "failed");
  return (
    <ul className={own.checks} aria-label="Checks">
      {failed.length === 0 ? (
        <li className={own.passed}>AdVegaX&apos;s checks passed.</li>
      ) : (
        failed.map((c, i) => (
          <li key={`${c.check}-${c.reason}-${i}`} className={own.failed}>
            <strong>{CHECK_GROUPS[c.check] ?? c.check}:</strong> {reasonText(c.reason)}
          </li>
        ))
      )}
      {dryRun && dryRun.result !== "skipped" ? (
        <li className={dryRun.result === "passed" ? own.passed : own.failed}>
          <strong>{CHECK_GROUPS.dry_run}:</strong>{" "}
          {dryRun.result === "passed"
            ? "the platform accepted the change in a test, without making it."
            : reasonText(dryRun.reason)}
        </li>
      ) : null}
    </ul>
  );
}

// ------------------------------------------------------------------ list
export function ChangesPage() {
  const org = useCurrentOrganization();
  const [filter, setFilter] = useState("open");
  const actions = useActions(org.id, filter);
  return (
    <section aria-labelledby="changes-title">
      <PageHeading id="changes-title">Changes</PageHeading>
      <p className={styles.muted}>
        Every change AdVegaX makes to your Google Ads and Meta campaigns: who asked, who approved,
        what was sent and whether the platform shows it. Nothing is sent without approval by an
        owner or admin.
      </p>
      <div className={styles.toolbar}>
        <SelectField
          label="Show"
          options={FILTERS}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      {actions.error ? <Alert tone="error">{messageFor(actions.error)}</Alert> : null}
      {actions.isPending ? <p role="status">Loading changes…</p> : null}
      {actions.data?.length === 0 ? (
        <p role="status">
          {filter === "open"
            ? "No changes are waiting. Request one from a campaign's page."
            : "No changes here yet."}
        </p>
      ) : null}
      {actions.data?.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>Changes, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Change</th>
                <th scope="col">Campaign</th>
                <th scope="col">Status</th>
                <th scope="col">Requested</th>
              </tr>
            </thead>
            <tbody>
              {actions.data.map((a) => (
                <tr key={a.id}>
                  <th scope="row">
                    <Link href={`/orgs/${org.id}/changes/${a.id}`}>{describe(a, moneyOf(a))}</Link>
                    {a.undo_of ? <span className={styles.muted}> (undo)</span> : null}
                  </th>
                  <td>
                    {a.campaign.name}
                    <br />
                    <span className={styles.muted}>
                      {a.provider === "meta_ads" ? "Meta" : "Google Ads"}
                      {a.campaign.ad_account_name ? ` · ${a.campaign.ad_account_name}` : ""}
                    </span>
                  </td>
                  <td>
                    <Status status={a.status} />
                  </td>
                  <td>{when(a.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ one change
function Decisions({ action }: { action: Action }) {
  const org = useCurrentOrganization();
  const approve = useApproveChange(org.id);
  const reject = useRejectChange(org.id);
  const cancel = useCancelChange(org.id);
  const undo = useUndoChange(org.id);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<{ text: string; href?: string } | null>(null);
  const approver = canApproveChanges(org.role);
  const requester = canRequestChanges(org.role);
  const pending = action.status === "pending";
  const cancellable = ["pending", "approved", "queued"].includes(action.status);
  const busy = approve.isPending || reject.isPending || cancel.isPending || undo.isPending;
  const onError = (e: unknown) => setError(e);

  const submitReject = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    reject.mutate(
      { id: action.id, reason: reason.trim() },
      { onSuccess: () => setRejecting(false), onError },
    );
  };

  if (!pending && !cancellable && !action.can_undo) return null;
  return (
    <section aria-labelledby="decide-title" className={styles.panel}>
      <h2 id="decide-title">What next</h2>
      {error ? (
        <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
          {messageFor(error)}
          {error instanceof ApiError && error.details.length ? (
            <ul>
              {error.details.map((d, i) => (
                <li key={i}>{reasonText(d.reason ?? null)}</li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}
      {notice ? (
        <Alert tone="success">
          {notice.text} {notice.href ? <Link href={notice.href}>Open it</Link> : null}
        </Alert>
      ) : null}
      <div className={own.actions}>
        {pending && approver ? (
          <Button
            busy={approve.isPending}
            disabled={busy}
            onClick={() => {
              setError(null);
              approve.mutate(action.id, { onError });
            }}
          >
            Approve and send
          </Button>
        ) : null}
        {pending && approver && !rejecting ? (
          <Button variant="secondary" disabled={busy} onClick={() => setRejecting(true)}>
            Reject
          </Button>
        ) : null}
        {cancellable && requester ? (
          <Button
            variant="secondary"
            busy={cancel.isPending}
            disabled={busy}
            onClick={() => {
              setError(null);
              cancel.mutate(action.id, { onError });
            }}
          >
            Cancel this change
          </Button>
        ) : null}
        {action.can_undo && requester ? (
          <Button
            variant="secondary"
            busy={undo.isPending}
            disabled={busy}
            onClick={() => {
              setError(null);
              undo.mutate(action.id, {
                onSuccess: (made) =>
                  setNotice({
                    text: "The undo was requested and waits for approval.",
                    href: `/orgs/${org.id}/changes/${made.id}`,
                  }),
                onError,
              });
            }}
          >
            Undo this change
          </Button>
        ) : null}
      </div>
      {pending && !approver ? (
        <p className={styles.muted}>An owner or admin approves or rejects this change.</p>
      ) : null}
      {rejecting ? (
        <form onSubmit={submitReject} noValidate aria-label="Reject the change">
          <TextField
            label="Why is it rejected?"
            required
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className={own.actions}>
            <Button
              type="submit"
              variant="danger"
              busy={reject.isPending}
              disabled={!reason.trim()}
            >
              Reject
            </Button>
            <Button variant="secondary" onClick={() => setRejecting(false)}>
              Keep it
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function State({
  title,
  state,
  money,
}: {
  title: string;
  state: Action["previous"] | null | undefined;
  money: (v: string) => string;
}) {
  if (!state) return null;
  return (
    <>
      <dt>{title}</dt>
      <dd>
        {state.status ? statusWords(state.status) : "Status not known"}
        {state.daily_budget ? ` · ${money(state.daily_budget)} a day` : ""}
        {state.budget_level === "ad_group" ? " · budget on the ad sets" : ""}
      </dd>
    </>
  );
}

function statusWords(status: string) {
  return status === "active" ? "Running" : status === "paused" ? "Paused" : status;
}

function Detail({ actionId }: { actionId: string }) {
  const org = useCurrentOrganization();
  const action = useAction(org.id, actionId);
  if (action.error) {
    if (action.error instanceof ApiError && action.error.status === 404) return <NotFound />;
    return <Alert tone="error">{messageFor(action.error)}</Alert>;
  }
  const a = action.data;
  if (!a) return <p role="status">Loading change…</p>;
  const money = moneyOf(a);
  return (
    <section aria-labelledby="change-title">
      <p>
        <Link href={`/orgs/${org.id}/changes`}>← All changes</Link>
      </p>
      <PageHeading id="change-title">{describe(a, money)}</PageHeading>
      <p>
        <Status status={a.status} />
      </p>
      {a.error_code && a.status !== "succeeded" ? (
        <Alert tone={a.status === "unknown" ? "info" : "error"}>{reasonText(a.error_code)}</Alert>
      ) : null}
      {a.verification ? (
        <Alert tone={a.verification === "verified" ? "success" : "info"}>
          {VERIFICATION[a.verification]}
        </Alert>
      ) : null}
      <dl className={`${styles.panel} ${styles.facts}`}>
        <dt>Campaign</dt>
        <dd>
          <Link href={`/orgs/${org.id}/advertising/campaigns/${a.campaign.id}`}>
            {a.campaign.name}
          </Link>{" "}
          ({a.provider === "meta_ads" ? "Meta" : "Google Ads"}
          {a.campaign.ad_account_name ? `, ${a.campaign.ad_account_name}` : ""})
        </dd>
        <State title="Before" state={a.previous} money={money} />
        <State title="Read back after" state={a.observed} money={money} />
        <dt>Requested</dt>
        <dd>{when(a.created_at)}</dd>
        {a.decided_at ? (
          <>
            <dt>{a.status === "rejected" ? "Rejected" : "Approved"}</dt>
            <dd>
              {when(a.decided_at)}
              {a.decision_reason ? ` — “${a.decision_reason}”` : ""}
            </dd>
          </>
        ) : null}
        {a.submitted_at ? (
          <>
            <dt>Sent</dt>
            <dd>{when(a.submitted_at)}</dd>
          </>
        ) : null}
        {a.undo_of ? (
          <>
            <dt>Undoes</dt>
            <dd>
              <Link href={`/orgs/${org.id}/changes/${a.undo_of}`}>the earlier change</Link>
            </dd>
          </>
        ) : null}
      </dl>
      <Decisions action={a} />
      <section aria-labelledby="checks-title" className={styles.section}>
        <h2 id="checks-title">Checks when requested</h2>
        <CheckList checks={a.checks} dryRun={a.dry_run} />
      </section>
      {a.platform_request ? (
        <section aria-labelledby="sent-title" className={styles.section}>
          <h2 id="sent-title">Exactly what was sent</h2>
          <pre className={own.code}>{JSON.stringify(a.platform_request, null, 2)}</pre>
        </section>
      ) : null}
      <section aria-labelledby="history-title" className={styles.section}>
        <h2 id="history-title">History</h2>
        <ol className={own.history}>
          {(a.events ?? []).map((e, i) => (
            <li key={i}>
              {when(e.created_at)} — <Status status={e.status} />{" "}
              <span className={styles.muted}>
                {e.actor_type === "worker" ? "by AdVegaX" : "by a person"}
                {typeof e.detail.reason === "string" ? ` · ${reasonText(e.detail.reason)}` : ""}
              </span>
            </li>
          ))}
        </ol>
      </section>
    </section>
  );
}

function NotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="change-missing">
      <PageHeading id="change-missing">Change not found</PageHeading>
      <p>This change does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/changes`}>Back to changes</Link>
      </p>
    </section>
  );
}

export function ChangeDetailPage() {
  const params = useParams<{ actionId: string }>();
  const id = params.actionId ?? "";
  if (!UUID.test(id)) return <NotFound />;
  return <Detail actionId={id} />;
}
