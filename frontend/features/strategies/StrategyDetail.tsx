"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import ui from "@/components/ui/ui.module.css";
import styles from "@/features/advertising/advertising.module.css";
import { providerName } from "@/features/advertising/labels";
import { formatFigure, type ReportingCurrency } from "@/features/overview/labels";
import {
  OrganizationNotFound,
  useCurrentOrganization,
} from "@/features/organizations/OrganizationShell";
import type { Organization } from "@/features/organizations/api";
import { formatDateTime } from "@/features/organizations/options";
import { useCreativeSets, useGenerateCreatives } from "@/features/creatives/api";
import { creativeReasonText } from "@/features/creatives/labels";
import { canManageCreatives, canManageStrategies } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import type { Availability } from "@/lib/format/availability";
import { formatMoney } from "@/lib/format/money";

import {
  asPlan,
  useArchive,
  useMarkReady,
  useStrategy,
  useUpdateStrategy,
  type Plan,
  type Strategy,
} from "./api";
import {
  CAMPAIGN_TYPES,
  OBJECTIVES,
  PERIODS,
  RISKS,
  STATUS,
  TARGETS,
  campaignType,
  errorReasons,
  reasonText,
  statusLabel,
} from "./labels";
import own from "./strategies.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function money(strategy: Strategy): ReportingCurrency {
  return {
    currency: strategy.budget.currency,
    minorUnits: strategy.budget.currency_minor_units,
  };
}

/** The AdVegaX figures a point relies on, as the planner saw them. */
function EvidenceList({ keys, strategy }: { keys: readonly string[]; strategy: Strategy }) {
  return (
    <ul className={own.evidence} aria-label="Based on">
      {keys.map((key) => {
        const e = strategy.evidence[key];
        if (!e) return <li key={key}>{key}: not in the figures the planner saw</li>;
        const figure = {
          value: e.value,
          availability: e.availability as Availability,
          reason: e.reason,
        };
        return (
          <li key={key}>
            {e.label}: {formatFigure(figure, e.unit, money(strategy))}
          </li>
        );
      })}
    </ul>
  );
}

function targetRange(strategy: Strategy, metric: string, low: number, high: number): string {
  const unit = TARGETS[metric]?.unit ?? "multiple";
  if (unit === "multiple") return `${low}× to ${high}×`;
  const { currency, minorUnits } = money(strategy);
  return `${formatMoney(String(low), currency, minorUnits)} to ${formatMoney(String(high), currency, minorUnits)}`;
}

function StrategyView({ strategy }: { strategy: Strategy }) {
  const plan = asPlan(strategy);
  const { currency, minorUnits } = money(strategy);
  return (
    <>
      <section aria-labelledby="plan-summary" className={styles.section}>
        <h2 id="plan-summary">Summary</h2>
        <p>
          <strong>Objective:</strong> {OBJECTIVES[plan.objective] ?? plan.objective}
        </p>
        <p>{plan.summary}</p>
        <p>
          <strong>Positioning:</strong> {plan.positioning}
        </p>
        <p>
          <strong>Budget:</strong> {formatMoney(strategy.budget.amount, currency, minorUnits)}{" "}
          {PERIODS[strategy.budget.period]}
        </p>
      </section>
      <section aria-labelledby="plan-platforms" className={styles.section}>
        <h2 id="plan-platforms">Platforms</h2>
        <ul className={own.platforms}>
          {plan.platforms.map((p) => {
            const amount = strategy.budget_amounts[p.platform];
            return (
              <li key={p.platform} className={own.platform}>
                <h3>
                  {providerName(p.platform)} — {campaignType(p.platform, p.campaign_type)}
                </h3>
                <p>
                  <span className={own.amount}>
                    {amount ? formatMoney(amount.amount, currency, minorUnits) : "—"}
                  </span>{" "}
                  {PERIODS[strategy.budget.period]} ({p.budget_share_percent}% of the budget)
                  {amount && strategy.budget.period === "monthly"
                    ? `, about ${formatMoney(amount.daily, currency, minorUnits)} per day`
                    : ""}
                </p>
                <p>
                  <strong>Who to reach:</strong> {p.audience}
                </p>
                <p>
                  <strong>Why:</strong> {p.reasoning}
                </p>
                <EvidenceList keys={p.evidence} strategy={strategy} />
              </li>
            );
          })}
        </ul>
        <p className={styles.muted}>
          AdVegaX worked out the amounts from the shares; together they are exactly your budget.
        </p>
      </section>
      <section aria-labelledby="plan-angles" className={styles.section}>
        <h2 id="plan-angles">Angles to lead with</h2>
        <ul>
          {plan.angles.map((a, i) => (
            <li key={`${i}-${a.angle}`}>
              {a.angle}
              <EvidenceList keys={a.evidence} strategy={strategy} />
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="plan-targets" className={styles.section}>
        <h2 id="plan-targets">Targets to watch</h2>
        {plan.targets.length === 0 ? (
          <p className={styles.muted}>No targets.</p>
        ) : (
          <ul>
            {plan.targets.map((t) => (
              <li key={t.metric}>
                <strong>{TARGETS[t.metric]?.label ?? t.metric}:</strong>{" "}
                {targetRange(strategy, t.metric, t.low, t.high)}
                <EvidenceList keys={t.evidence} strategy={strategy} />
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="plan-risks" className={styles.section}>
        <h2 id="plan-risks">Risks and assumptions</h2>
        {plan.risks.length === 0 ? <p className={styles.muted}>No risks named.</p> : null}
        <ul>
          {plan.risks.map((r, i) => (
            <li key={`risk-${i}`}>
              <strong>{RISKS[r.code] ?? r.code}:</strong> {r.text}
            </li>
          ))}
          {plan.assumptions.map((a, i) => (
            <li key={`assumption-${i}`}>
              <strong>Assumption:</strong> {a}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function TextArea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className={ui.field}>
      <label htmlFor={id} className={ui.label}>
        {label}
      </label>
      <textarea
        id={id}
        className={`${ui.input} ${own.textarea}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function EditForm({
  org,
  strategy,
  onDone,
}: {
  org: Organization;
  strategy: Strategy;
  onDone: () => void;
}) {
  const [plan, setPlan] = useState<Plan>(() => structuredClone(asPlan(strategy)));
  const [shares, setShares] = useState(() =>
    asPlan(strategy).platforms.map((p) => String(p.budget_share_percent)),
  );
  const [amount, setAmount] = useState(strategy.budget.amount);
  const [period, setPeriod] = useState(strategy.budget.period);
  const update = useUpdateStrategy(org.id, strategy.id);
  const change = (next: Partial<Plan>) => setPlan((now) => ({ ...now, ...next }));
  const changePlatform = (i: number, next: Partial<Plan["platforms"][number]>) =>
    setPlan((now) => ({
      ...now,
      platforms: now.platforms.map((p, j) => (j === i ? { ...p, ...next } : p)),
    }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const edited: Plan = {
      ...plan,
      platforms: plan.platforms.map((p, i) => ({
        ...p,
        budget_share_percent: Number(shares[i]),
      })),
    };
    update.mutate(
      {
        strategy: edited as unknown as Record<string, unknown>,
        budget: { amount: amount.trim(), period },
      },
      { onSuccess: onDone },
    );
  };

  const error = update.error;
  return (
    <form className={own.form} onSubmit={submit} noValidate aria-label="Edit the strategy">
      <TextArea label="Summary" value={plan.summary} onChange={(v) => change({ summary: v })} />
      <TextArea
        label="Positioning"
        value={plan.positioning}
        onChange={(v) => change({ positioning: v })}
      />
      {plan.platforms.map((p, i) => (
        <fieldset key={p.platform} className={own.platform}>
          <legend>{providerName(p.platform)}</legend>
          <SelectField
            label={`Campaign type on ${providerName(p.platform)}`}
            options={Object.entries(CAMPAIGN_TYPES[p.platform] ?? {}).map(([value, label]) => ({
              value,
              label,
            }))}
            value={p.campaign_type}
            onChange={(e) => changePlatform(i, { campaign_type: e.target.value })}
          />
          <TextField
            label={`Share of the budget for ${providerName(p.platform)} (%)`}
            inputMode="decimal"
            value={shares[i] ?? ""}
            onChange={(e) => setShares((now) => now.map((s, j) => (j === i ? e.target.value : s)))}
            required
          />
          <TextArea
            label={`Who to reach on ${providerName(p.platform)}`}
            value={p.audience}
            onChange={(v) => changePlatform(i, { audience: v })}
          />
          <TextArea
            label={`Why ${providerName(p.platform)}`}
            value={p.reasoning}
            onChange={(v) => changePlatform(i, { reasoning: v })}
          />
        </fieldset>
      ))}
      <div className={own.row}>
        <TextField
          label={`Budget (${strategy.budget.currency})`}
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />
        <SelectField
          label="Budget period"
          options={[
            { value: "daily", label: "Per day" },
            { value: "monthly", label: "Per month" },
          ]}
          value={period}
          onChange={(e) => setPeriod(e.target.value as "daily" | "monthly")}
        />
      </div>
      <p className={styles.muted}>
        Your changes are checked the same way as the planner&apos;s answer, against today&apos;s
        figures. The shares must add up to 100%. A changed strategy is a draft again.
      </p>
      {error ? (
        <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
          <p>{messageFor(error)}</p>
          {error instanceof ApiError && error.details.length ? (
            <ul className={own.reasons}>
              {errorReasons(error.details).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          ) : null}
        </Alert>
      ) : null}
      <div className={own.actions}>
        <Button type="submit" busy={update.isPending}>
          Save changes
        </Button>
        <Button variant="secondary" onClick={onDone} disabled={update.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Actions({
  org,
  strategy,
  onEdit,
}: {
  org: Organization;
  strategy: Strategy;
  onEdit: () => void;
}) {
  const ready = useMarkReady(org.id, strategy.id);
  const archive = useArchive(org.id, strategy.id);
  const [confirm, setConfirm] = useState(false);
  const error = ready.error ?? archive.error;
  if (strategy.status === "archived") {
    return <p className={styles.muted}>This strategy is archived. It is kept as it was.</p>;
  }
  return (
    <>
      {error ? <Alert tone="error">{messageFor(error)}</Alert> : null}
      <div className={own.actions}>
        <Button variant="secondary" onClick={onEdit}>
          Edit
        </Button>
        {strategy.status === "draft" ? (
          <Button busy={ready.isPending} onClick={() => ready.mutate(undefined)}>
            Mark ready for the campaign builder
          </Button>
        ) : null}
        <Button variant="danger" onClick={() => setConfirm(true)}>
          Archive
        </Button>
      </div>
      <ConfirmDialog
        open={confirm}
        title="Archive this strategy?"
        confirmLabel="Archive"
        busy={archive.isPending}
        onCancel={() => setConfirm(false)}
        onConfirm={() => archive.mutate(undefined, { onSettled: () => setConfirm(false) })}
      >
        It is kept, but it can no longer be changed or used by the campaign builder.
      </ConfirmDialog>
    </>
  );
}

/** Phase 9: ad copy is drafted from a strategy marked ready; the sets made so far. */
function StrategyCreatives({ org, strategy }: { org: Organization; strategy: Strategy }) {
  const router = useRouter();
  const sets = useCreativeSets(org.id, strategy.id);
  const generate = useGenerateCreatives(org.id);
  const error = generate.error;
  const reasons =
    error instanceof ApiError
      ? error.details.map((d) =>
          d.reason ? (creativeReasonText(d.reason) ?? reasonText(d.reason)) : "",
        )
      : [];
  return (
    <section aria-labelledby="strategy-creatives" className={styles.section}>
      <h2 id="strategy-creatives">Creatives</h2>
      {sets.data && sets.data.length ? (
        <ul>
          {sets.data.map((s) => (
            <li key={s.id}>
              <Link href={`/orgs/${org.id}/creatives/${s.id}`}>
                Drafted on {formatDateTime(s.created_at)}
              </Link>{" "}
              — {s.approved} of {s.concepts} approved
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>No creatives yet.</p>
      )}
      {strategy.status !== "ready" ? (
        <p className={styles.muted}>Mark the strategy ready to make creatives from it.</p>
      ) : canManageCreatives(org.role) ? (
        <>
          {error ? (
            <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
              <p>{messageFor(error)}</p>
              {reasons.length ? (
                <ul className={own.reasons}>
                  {reasons.map((r, i) => (
                    <li key={`r-${i}`}>{r}</li>
                  ))}
                </ul>
              ) : null}
            </Alert>
          ) : null}
          {generate.isPending ? (
            <p role="status">Writing and checking the ad copy — this can take up to a minute.</p>
          ) : null}
          <Button
            busy={generate.isPending}
            onClick={() =>
              generate.mutate(strategy.id, {
                onSuccess: (made) => router.push(`/orgs/${org.id}/creatives/${made.id}`),
              })
            }
          >
            Make creatives
          </Button>
        </>
      ) : null}
    </section>
  );
}

function LoadedStrategy({ org, strategyId }: { org: Organization; strategyId: string }) {
  const query = useStrategy(org.id, strategyId);
  const [editing, setEditing] = useState(false);
  if (query.error) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return <OrganizationNotFound />;
    }
    return <Alert tone="error">{messageFor(query.error)}</Alert>;
  }
  if (!query.data) return <p role="status">Loading…</p>;
  const strategy = query.data;
  const run = strategy.ai_run;
  const manage = canManageStrategies(org.role);
  return (
    <section aria-labelledby="strategy-title">
      <p>
        <Link href={`/orgs/${org.id}/strategies`}>All strategies</Link>
      </p>
      <PageHeading id="strategy-title">
        {strategy.product_title ?? "Product no longer in the store"}
      </PageHeading>
      <p>
        <span className={`${styles.status} ${styles[STATUS[strategy.status]?.tone ?? "off"]}`}>
          {statusLabel(strategy.status)}
        </span>
      </p>
      <p className={styles.muted}>
        Drafted by {run.provider === "anthropic" ? "Claude" : run.provider} ({run.model}), prompt{" "}
        {run.prompt_name} {run.prompt_version}, on {formatDateTime(run.created_at)}. Checked by
        AdVegaX before it was shown
        {strategy.edited_at ? `; last edited on ${formatDateTime(strategy.edited_at)}` : ""}.
        Nothing has been created at Google or Meta.
      </p>
      {manage && !editing ? (
        <Actions org={org} strategy={strategy} onEdit={() => setEditing(true)} />
      ) : null}
      {!editing ? <StrategyCreatives org={org} strategy={strategy} /> : null}
      {editing ? (
        <EditForm org={org} strategy={strategy} onDone={() => setEditing(false)} />
      ) : (
        <StrategyView strategy={strategy} />
      )}
    </section>
  );
}

/** One campaign strategy with its figures, and editing, marking ready and archiving. */
export function StrategyDetail() {
  const org = useCurrentOrganization();
  const params = useParams<{ strategyId: string }>();
  const id = params.strategyId ?? "";
  if (!UUID.test(id)) return <OrganizationNotFound />;
  return <LoadedStrategy org={org} strategyId={id} />;
}
