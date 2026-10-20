import type { Metadata } from "next";

import { AnalyticsPropertyPage } from "@/features/analytics/AnalyticsPropertyPage";

export const metadata: Metadata = { title: "Analytics property" };

export default function Page() {
  return <AnalyticsPropertyPage />;
}
