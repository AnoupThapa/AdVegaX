"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import styles from "@/features/advertising/advertising.module.css";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useBilling, useCheckout, usePlans, usePortal, type Billing, type Plan } from "./api";

type Interval = "month" | "year";

const day = (value: string | null | undefined) =>
  value ? new Intl.DateTimeFormat(undefined, { dateStyle: "long" }).format(new Date(value)) : "";

export function money(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency.toUpperCase(),
    minimumFractionDigits: 0,
  }).format(minor / 100);
}

/** One sentence for where the organization stands (shared with the banner). */
export function standingText(b: Billing): string {
  const plan = b.plan?.name ?? "";
  switch (b.status) {
    case "off":
      return "Billing is switched off for this AdVegaX installation: no plan limits apply.";
    case "complimentary":
      return `This organization is complimentary: ${plan} limits, never charged.`;
    case "trialing":
      return `Free trial of the ${plan} plan until ${day(b.trial_ends_at)}. No card needed.`;
    case "past_due":
      return `A payment failed. Everything keeps working until ${day(b.grace_ends_at)}; update the card in Stripe before then.`;
    case "read_only":
      return "This organization is read-only: everything stays visible, but nothing new is imported, changed or generated. Nothing has been deleted. Choose a plan or update the card to continue.";
    default:
      if (b.cancel_at_period_end) {
        return `${plan} plan. It has been cancelled and ends on ${day(b.current_period_end)}.`;
      }
      return `${plan} plan, ${b.interval === "year" ? "yearly" : "monthly"}. It renews on ${day(b.current_period_end)}.`;
  }
}

/** The Billing page (Phase 13): plan, dates, usage against limits; owners act in Stripe. */
export function BillingPage() {
  const org = useCurrentOrganization();
  const search = useSearchParams();
  const returned = search.get("checkout") === "done";
  const billing = useBilling(org.id);
  return (
    <section aria-labelledby="billing-title">
      <PageHeading id="billing-title">Billing</PageHeading>
      {returned && billing.data?.checkout_available ? (
        <Alert tone="success">
          Thank you. Your plan shows here as soon as Stripe confirms the payment, usually within a
          minute.
        </Alert>
      ) : null}
      {billing.error ? <Alert tone="error">{messageFor(billing.error)}</Alert> : null}
      {billing.isPending ? <p role="status">Loading…</p> : null}
      {billing.data ? <Loaded orgId={org.id} billing={billing.data} /> : null}
    </section>
  );
}

function Loaded({ orgId, billing }: { orgId: string; billing: Billing }) {
  const portal = usePortal(orgId);
  const tone = billing.read_only || billing.status === "past_due" ? "error" : "info";
  return (
    <>
      <Alert tone={tone}>{standingText(billing)}</Alert>
      {billing.enabled ? <Usage billing={billing} /> : null}
      {billing.portal_available ? (
        <div className={styles.section}>
          <h2>Card, invoices and plan changes</h2>
          <p className={styles.muted}>
            Stripe&apos;s customer portal keeps your card and invoices. Upgrades apply at once;
            downgrades and cancellations at the end of the paid period.
          </p>
          <Button variant="secondary" busy={portal.isPending} onClick={() => portal.mutate()}>
            Manage billing in Stripe
          </Button>
          {portal.error ? <Alert tone="error">{messageFor(portal.error)}</Alert> : null}
        </div>
      ) : null}
      {billing.checkout_available ? <Choose orgId={orgId} /> : null}
      {billing.enabled && !billing.can_manage ? (
        <p className={styles.muted}>Only the organization&apos;s owners can change the plan.</p>
      ) : null}
    </>
  );
}

const ROWS = [
  { key: "stores", label: "Stores" },
  { key: "ad_accounts", label: "Ad accounts" },
  { key: "members", label: "Members and open invitations" },
] as const;

function Usage({ billing }: { billing: Billing }) {
  const limits = billing.plan?.limits;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption>Usage</caption>
        <thead>
          <tr>
            <th scope="col">What</th>
            <th scope="col" className={styles.num}>
              Used
            </th>
            <th scope="col" className={styles.num}>
              Plan allows
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.label}</th>
              <td className={styles.num}>{billing.usage[row.key]}</td>
              <td className={styles.num}>{limits ? limits[row.key] : "—"}</td>
            </tr>
          ))}
          <tr>
            <th scope="row">AI runs today</th>
            <td className={styles.num}>{billing.usage.ai_runs_today}</td>
            <td className={styles.num}>{limits ? limits.ai_runs_per_day : "—"}</td>
          </tr>
          <tr>
            <th scope="row">Autopilot</th>
            <td className={styles.num}>—</td>
            <td className={styles.num}>{limits ? (limits.autopilot ? "Yes" : "No") : "—"}</td>
          </tr>
        </tbody>
      </table>
      <p className={styles.muted}>
        Limits are checked when something is added. Nothing you have is removed if you move to a
        smaller plan.
      </p>
    </div>
  );
}

function Choose({ orgId }: { orgId: string }) {
  const plans = usePlans();
  const checkout = useCheckout(orgId);
  const [interval, setInterval] = useState<Interval>("month");
  const [chosen, setChosen] = useState<string | null>(null);
  const conflict = checkout.error instanceof ApiError && checkout.error.status === 409;
  return (
    <div className={styles.section}>
      <h2>Choose a plan</h2>
      <fieldset>
        <legend>Pay</legend>
        {(["month", "year"] as const).map((value) => (
          <label key={value}>
            <input
              type="radio"
              name="interval"
              value={value}
              checked={interval === value}
              onChange={() => setInterval(value)}
            />{" "}
            {value === "month" ? "Monthly" : "Yearly (two months free)"}
          </label>
        ))}
      </fieldset>
      {plans.error ? <Alert tone="error">{messageFor(plans.error)}</Alert> : null}
      <ul className={styles.list} aria-label="Plans">
        {plans.data?.map((plan) => (
          <PlanCard
            key={plan.code}
            plan={plan}
            interval={interval}
            busy={checkout.isPending && chosen === plan.code}
            onChoose={() => {
              setChosen(plan.code);
              checkout.mutate({ plan: plan.code, interval });
            }}
          />
        ))}
      </ul>
      <p className={styles.muted}>
        Prices include GST for Australian customers. You pay on Stripe&apos;s own page; AdVegaX
        never sees your card.
      </p>
      {checkout.error && !conflict ? (
        <Alert tone="error">{messageFor(checkout.error)}</Alert>
      ) : null}
      {conflict ? (
        <Alert tone="error">
          This organization already has a plan or is not charged. Reload the page to see it.
        </Alert>
      ) : null}
    </div>
  );
}

function PlanCard({
  plan,
  interval,
  busy,
  onChoose,
}: {
  plan: Plan;
  interval: Interval;
  busy: boolean;
  onChoose: () => void;
}) {
  const l = plan.limits;
  const price = interval === "month" ? plan.monthly : plan.yearly;
  return (
    <li className={styles.card}>
      <h3 className={styles.cardTitle}>{plan.name}</h3>
      <p>
        <strong>{money(price, plan.currency)}</strong> a {interval}
      </p>
      <ul>
        <li>
          {l.stores} {l.stores === 1 ? "store" : "stores"}
        </li>
        <li>{l.ad_accounts} ad accounts</li>
        <li>{l.members} members</li>
        <li>{l.ai_runs_per_day} AI runs a day</li>
        <li>{l.autopilot ? "Autopilot" : "No autopilot"}</li>
      </ul>
      <Button busy={busy} onClick={onChoose} aria-label={`Choose ${plan.name}`}>
        Choose {plan.name}
      </Button>
    </li>
  );
}
