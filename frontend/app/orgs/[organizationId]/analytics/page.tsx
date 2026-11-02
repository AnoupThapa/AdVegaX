import type { Metadata } from "next";

import { AnalyticsPropertiesPage } from "@/features/analytics/AnalyticsPropertiesPage";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return <AnalyticsPropertiesPage />;
}
