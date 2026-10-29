"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import ui from "@/components/ui/ui.module.css";
import styles from "@/features/advertising/advertising.module.css";
import { CheckList, Status as ChangeStatus } from "@/features/changes/ChangesPages";
import own from "@/features/changes/changes.module.css";
import { reasonText } from "@/features/changes/labels";
import type { Organization } from "@/features/organizations/api";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canApproveChanges, canRequestChanges } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useApproveRecommendation,
  useRecommendation,
  useRecommendationDone,
  useRecommendations,
  useRefreshRecommendations,
  useRejectRecommendation,
  type Recommendation,
  type RecommendationList,
  type RejectReason,
} from "./api";
import {
  AI_PROBLEMS,
  CLOSED_REASONS,
  CONFIDENCE_LABELS,
  FIGURE_LABELS,
  NOTE_TEXT,
  PROFIT_REASONS,
  REJECT_REASONS,
  kindLabel,
  statusOf,
} from "./labels";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FILTERS = [
  { value: "open", label: "Open" },
  { value: "decided", label: "Approved, rejected or looked into" },
  { value: "closed", label: "Expired or out of date" },
];
const when = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(value),
      )
    : "—";
const day = (value: string | undefined) =>
  value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
        new Date(`${value}T00:00:00Z`),
      )
    : "—";

function Status({ status }: { status: string }) {
  const s = statusOf(status);
  return <span className={`${styles.status} ${styles[s.tone]}`}>{s.label}</span>;
}

function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? error.details : [];
  return (
    <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
      {messageFor(error)}
      {details.length ? (
        <ul>
          {details.map((d, i) => (
            <li key={i}>{CLOSED_REASONS[d.reason ?? ""] ?? reasonText(d.reason ?? null)}</li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

function subjectOf(r: Recommendation) {
  if (r.campaign) {
    return `${r.campaign.name} · ${r.campaign.provider === "meta_ads" ? "Meta" : "Google Ads"}`;
  }
  const platform = r.funnel?.platform as string | null | undefined;
  if (platform) return `${platform === "meta_ads" ? "Meta" : "Google Ads"}'s own funnel`;
  return "Your business's funnel";
}

function Figures({ r }: { r: Recommendation }) {
  const entries = Object.entries(r.figures);
  if (!entries.length) return null;
  return (
    <dl className={styles.facts} aria-label="The figures behind it">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt>{FIGURE_LABELS[key] ?? key}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

function Summary({ data, org }: { data: RecommendationList; org: Organization }) {
  const refresh = useRefreshRecommendations(org.id);
  const run = data.summary.last_run as Record<string, unknown> | null | undefined;
  const allowed = canRequestChanges(org.role);
  return (
    <div className={styles.panel}>
      {!data.summary.enabled ? (
        <Alert tone="info">
          Recommendations are switched off for this AdVegaX installation. No new advice is made.
        </Alert>
      ) : null}
      {run ? (
        <p>
          Last look: {when(run.ran_at as string)} — {String(run.campaigns_checked ?? 0)} running
          campaigns checked, {String(run.found ?? 0)} found.
        </p>
      ) : (
        <p>AdVegaX has not looked at your campaigns yet. It looks once a day.</p>
      )}
      {run && run.profit_rules === "skipped" ? (
        <p className={styles.muted}>
          The profit rules (losing money, held back by budget) were not used:{" "}
          {PROFIT_REASONS[String(run.profit_reason)] ?? "your gross margin is not known"}.
        </p>
      ) : null}
      {run && run.explained_by === "rules" && Number(run.found) > 0 ? (
        <p className={styles.muted}>
          Explained by AdVegaX&apos;s own rules
          {run.ai_problem
            ? `: ${AI_PROBLEMS[String(run.ai_problem)] ?? "the AI was not used"}`
            : ""}
          .
        </p>
      ) : null}
      <ErrorNotice error={refresh.error} />
      {allowed && data.summary.enabled ? (
        <div className={own.actions}>
          <Button
            variant="secondary"
            busy={refresh.isPending}
            disabled={data.summary.refreshes_left <= 0}
            onClick={() => refresh.mutate()}
          >
            Look again now
          </Button>
          <span className={styles.muted}>{data.summary.refreshes_left} left today</span>
        </div>
      ) : null}
    </div>
  );
}

function Card({ r, orgId }: { r: Recommendation; orgId: string }) {
  return (
    <li className={styles.panel}>
      <h2 className={styles.cardTitle}>
        <Link href={`/orgs/${orgId}/recommendations/${r.id}`}>{kindLabel(r.kind)}</Link>{" "}
        <Status status={r.status} />
      </h2>
      <p className={styles.muted}>
        {subjectOf(r)} · {CONFIDENCE_LABELS[r.confidence]}
        {r.explained_by === "rules" ? " · Rules only" : " · Explained by AI"}
      </p>
      <p>{r.explanation}</p>
      <p>
        <strong>Proposed:</strong> {r.proposal.text}
      </p>
      {r.status === "open" ? (
        <p className={styles.muted}>Valid until {when(r.expires_at)}</p>
      ) : null}
    </li>
  );
}

/** Recommendations: what AdVegaX noticed in your campaigns and what it proposes. */
export function RecommendationsPage() {
  const org = useCurrentOrganization();
  const [filter, setFilter] = useState("open");
  const list = useRecommendations(org.id, filter);
  return (
    <section aria-labelledby="recs-title">
      <PageHeading id="recs-title">Recommendations</PageHeading>
      <p className={styles.muted}>
        Once a day AdVegaX compares each running campaign with its own past, using its own figures.
        It proposes a change only when the figures support it, and nothing changes until you approve
        it — then it goes through Changes, checked again.
      </p>
      {list.data ? <Summary data={list.data} org={org} /> : null}
      <div className={styles.toolbar}>
        <SelectField
          label="Show"
          options={FILTERS}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      {list.error ? <Alert tone="error">{messageFor(list.error)}</Alert> : null}
      {list.isPending ? <p role="status">Loading recommendations…</p> : null}
      {list.data?.items.length === 0 ? (
        <p role="status">
          {filter === "open" ? "Nothing needs your attention right now." : "Nothing here yet."}
        </p>
      ) : null}
      {list.data?.items.length ? (
        <ul className={styles.cards} aria-label="Recommendations">
          {list.data.items.map((r) => (
            <Card key={r.id} r={r} orgId={org.id} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Decide({ r, org }: { r: Recommendation; org: Organization }) {
  const approve = useApproveRecommendation(org.id);
  const reject = useRejectRecommendation(org.id);
  const done = useRecommendationDone(org.id);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState<RejectReason | "">("");
  const [note, setNote] = useState("");
  const approver = canApproveChanges(org.role);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (reason) reject.mutate({ id: r.id, reason, note });
  };
  const change = Boolean(r.proposal.action_type);
  return (
    <section aria-labelledby="decide-title" className={styles.section}>
      <h2 id="decide-title">Your decision</h2>
      <ErrorNotice error={approve.error ?? reject.error ?? done.error} />
      {change ? (
        <p className={styles.muted}>
          {approver
            ? "Approving creates the change and sends it after AdVegaX and the platform check it again (unless your organization requires a second person)."
            : "Requesting creates the change; an owner or admin approves it under Changes."}
        </p>
      ) : (
        <p className={styles.muted}>No change is proposed: look into it, then mark it.</p>
      )}
      <div className={own.actions}>
        {change ? (
          <Button busy={approve.isPending} disabled={!r.ready} onClick={() => approve.mutate(r.id)}>
            {approver ? "Approve and send" : "Request this change"}
          </Button>
        ) : (
          <Button busy={done.isPending} onClick={() => done.mutate(r.id)}>
            Mark as looked into
          </Button>
        )}
        <Button variant="secondary" onClick={() => setRejecting(true)}>
          Reject
        </Button>
      </div>
      {change && !r.ready ? (
        <p className={styles.muted}>Before it can be approved, see the checks above.</p>
      ) : null}
      {rejecting ? (
        <form className={own.form} onSubmit={submit} noValidate aria-label="Reject this advice">
          <SelectField
            label="Why is it rejected?"
            placeholder="Choose a reason"
            options={REJECT_REASONS}
            value={reason}
            onChange={(e) => setReason(e.target.value as RejectReason | "")}
          />
          <div className={ui.field}>
            <label htmlFor="reject-note" className={ui.label}>
              Note (optional)
            </label>
            <textarea
              id="reject-note"
              className={ui.input}
              value={note}
              maxLength={500}
              rows={3}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <div className={own.actions}>
            <Button type="submit" busy={reject.isPending} disabled={!reason}>
              Reject this advice
            </Button>
            <Button variant="secondary" onClick={() => setRejecting(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

function Outcomes({ r }: { r: Recommendation }) {
  if (!r.outcomes.length) return null;
  const value = (side: Record<string, unknown>, key: string) => {
    const figures = (side.figures ?? {}) as Record<string, { value: string | null } | undefined>;
    return figures[key]?.value ?? "Not available";
  };
  return (
    <section aria-labelledby="outcomes-title" className={styles.section}>
      <h2 id="outcomes-title">What happened since</h2>
      <p className={styles.muted}>
        The campaign&apos;s figures before and after the change. This shows what happened, not that
        the change caused it.
      </p>
      {r.outcomes.map((o) => (
        <div key={o.after_days} className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>{o.after_days} days before and after</caption>
            <thead>
              <tr>
                <th scope="col">Figure</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
              </tr>
            </thead>
            <tbody>
              {["spend", "conversions", "cost_per_conversion", "conversion_value"].map((k) => (
                <tr key={k}>
                  <th scope="row">{FIGURE_LABELS[k]}</th>
                  <td>{value(o.before, k)}</td>
                  <td>{value(o.after, k)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}

function Detail({ id }: { id: string }) {
  const org = useCurrentOrganization();
  const one = useRecommendation(org.id, id);
  if (one.error) {
    if (one.error instanceof ApiError && one.error.status === 404) return <NotFound />;
    return <Alert tone="error">{messageFor(one.error)}</Alert>;
  }
  const r = one.data;
  if (!r) return <p role="status">Loading recommendation…</p>;
  return (
    <section aria-labelledby="rec-title">
      <p>
        <Link href={`/orgs/${org.id}/recommendations`}>← Recommendations</Link>
      </p>
      <PageHeading id="rec-title">{kindLabel(r.kind)}</PageHeading>
      <p className={styles.source}>
        {subjectOf(r)} · <Status status={r.status} /> · {CONFIDENCE_LABELS[r.confidence]} ·{" "}
        {r.explained_by === "rules" ? "Rules only" : "Explained by AI"}
      </p>
      {r.campaign ? (
        <p>
          <Link href={`/orgs/${org.id}/advertising/campaigns/${r.campaign.id}`}>
            Open the campaign
          </Link>
        </p>
      ) : null}
      <div className={styles.panel}>
        <p>{r.explanation}</p>
        <p className={styles.muted}>
          Recent days: {day(r.periods.from)} to {day(r.periods.to)}, compared with{" "}
          {day(r.periods.baseline_from)} to {day(r.periods.baseline_to)}. Figures in {r.currency};
          conversions are the platform&apos;s own.
        </p>
        <Figures r={r} />
      </div>
      <section aria-labelledby="proposal-title" className={styles.section}>
        <h2 id="proposal-title">Proposed</h2>
        <p>{r.proposal.text}</p>
        {r.note ? <p className={styles.muted}>{NOTE_TEXT[r.note] ?? r.note}</p> : null}
        {r.prechecks.length ? <CheckList checks={r.prechecks} /> : null}
        {r.assumptions.length ? (
          <>
            <h3>Assumptions</h3>
            <ul>
              {r.assumptions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </>
        ) : null}
        {r.risks.length ? (
          <>
            <h3>Risks</h3>
            <ul>
              {r.risks.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
      {r.status === "open" ? (
        <>
          <p className={styles.muted}>Valid until {when(r.expires_at)}.</p>
          {canRequestChanges(org.role) ? (
            <Decide r={r} org={org} />
          ) : (
            <p className={styles.muted}>Owners, admins and managers decide on advice.</p>
          )}
        </>
      ) : (
        <div className={styles.panel}>
          <p>
            <Status status={r.status} />
            {r.decided_at ? ` on ${when(r.decided_at)}` : ""}
            {r.decision_reason
              ? ` — ${REJECT_REASONS.find((x) => x.value === r.decision_reason)?.label}`
              : ""}
          </p>
          {r.decision_note ? <p>“{r.decision_note}”</p> : null}
          {r.closed_reason ? (
            <p className={styles.muted}>{CLOSED_REASONS[r.closed_reason]}</p>
          ) : null}
          {r.action ? (
            <p>
              The change: <ChangeStatus status={r.action.status} />{" "}
              <Link href={`/orgs/${org.id}/changes/${r.action.id}`}>Open it</Link>
            </p>
          ) : null}
        </div>
      )}
      <Outcomes r={r} />
    </section>
  );
}

function NotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="rec-missing">
      <PageHeading id="rec-missing">Recommendation not found</PageHeading>
      <p>This recommendation does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/recommendations`}>Back to recommendations</Link>
      </p>
    </section>
  );
}

export function RecommendationDetailPage() {
  const params = useParams<{ recommendationId: string }>();
  const id = params.recommendationId ?? "";
  if (!UUID.test(id)) return <NotFound />;
  return <Detail id={id} />;
}

/** On a campaign's page: its open advice. */
export function CampaignRecommendations({ campaignId }: { campaignId: string }) {
  const org = useCurrentOrganization();
  const list = useRecommendations(org.id, "open", campaignId);
  const items = list.data?.items ?? [];
  if (!items.length) return null;
  return (
    <section aria-labelledby="campaign-recs" className={styles.section}>
      <h2 id="campaign-recs">Recommendations</h2>
      <ul className={styles.cards} aria-label="Open recommendations for this campaign">
        {items.map((r) => (
          <li key={r.id}>
            <Link href={`/orgs/${org.id}/recommendations/${r.id}`}>{kindLabel(r.kind)}</Link> —{" "}
            {r.proposal.text}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** On the Overview: how much open advice there is. */
export function OverviewRecommendations({ org }: { org: Organization }) {
  const list = useRecommendations(org.id, "open");
  if (!list.data) return null;
  const count = list.data.summary.open;
  return (
    <div className={styles.panel}>
      <h2>Recommendations</h2>
      <p>
        {count === 0
          ? "Nothing needs your attention right now."
          : count === 1
            ? "1 piece of advice waits for your decision."
            : `${count} pieces of advice wait for your decision.`}
      </p>
      <p>
        <Link href={`/orgs/${org.id}/recommendations`}>Open recommendations</Link>
      </p>
    </div>
  );
}
