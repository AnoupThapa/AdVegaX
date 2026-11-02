"use client";

import { Alert } from "@/components/ui/Alert";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { canUpdateOrganization } from "@/features/organizations/permissions";
import { messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import { useAiUsage, type UsagePeriod } from "./api";

const count = (n: number) => new Intl.NumberFormat().format(n);

function Period({ title, period }: { title: string; period: UsagePeriod }) {
  return (
    <>
      <dt>{title}</dt>
      <dd>
        {count(period.runs)} runs ({count(period.succeeded)} accepted, {count(period.rejected)}{" "}
        rejected by AdVegaX&apos;s checks, {count(period.failed)} failed) ·{" "}
        {count(period.input_tokens)} tokens sent, {count(period.output_tokens)} received · estimated
        cost{" "}
        {period.estimated_cost_usd === null || period.estimated_cost_usd === undefined
          ? "unknown (no price set)"
          : formatMoney(period.estimated_cost_usd, "USD", 2)}
      </dd>
    </>
  );
}

/** Settings: the AI planner's use and estimated cost (owners and admins, Q-8-8). */
export function AiUsage({ org }: { org: Organization }) {
  const allowed = canUpdateOrganization(org.role);
  const usage = useAiUsage(org.id, allowed);
  if (!allowed) return null;
  return (
    <section aria-labelledby="ai-usage" className={styles.section}>
      <h2 id="ai-usage">AI planner use</h2>
      {usage.error ? (
        <Alert tone="error">{messageFor(usage.error)}</Alert>
      ) : !usage.data ? (
        <p role="status">Loading…</p>
      ) : (
        <>
          <p className={styles.muted}>
            {usage.data.ai_enabled
              ? `Up to ${count(usage.data.daily_limit)} strategies a day for this organization; ${count(usage.data.remaining_today)} left today (the day starts at midnight UTC).`
              : "The AI planner is switched off for this AdVegaX installation."}
          </p>
          <dl className={styles.facts}>
            <Period title="Today" period={usage.data.today} />
            <Period title="Last 30 days" period={usage.data.last_30_days} />
          </dl>
        </>
      )}
    </section>
  );
}
