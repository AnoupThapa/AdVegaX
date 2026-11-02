"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";

import { useBilling } from "./api";
import { standingText } from "./BillingPage";

const SOON_MS = 3 * 24 * 60 * 60 * 1000; // the trial reminder's 3 days (BILLING_TRIAL_REMINDER)

/** Above every organization page: trial ending, payment failed, read-only (Phase 13). */
export function BillingBanner({ orgId }: { orgId: string }) {
  const pathname = usePathname();
  const billing = useBilling(orgId);
  const [now] = useState(() => Date.now()); // when the page opened
  const b = billing.data;
  if (!b || pathname.endsWith("/billing")) return null;
  const ending =
    b.status === "trialing" &&
    b.trial_ends_at !== null &&
    new Date(b.trial_ends_at).getTime() - now <= SOON_MS;
  if (!(b.read_only || b.status === "past_due" || ending)) return null;
  return (
    <Alert tone={ending ? "info" : "error"}>
      {standingText(b)} <Link href={`/orgs/${orgId}/billing`}>Go to Billing</Link>
    </Alert>
  );
}
