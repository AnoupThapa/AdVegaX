import type { Metadata } from "next";

import { BillingPage } from "@/features/billing/BillingPage";

export const metadata: Metadata = { title: "Billing" };

export default function Page() {
  return <BillingPage />;
}
