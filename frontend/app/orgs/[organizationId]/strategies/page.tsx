import type { Metadata } from "next";

import { StrategiesPage } from "@/features/strategies/StrategiesPage";

export const metadata: Metadata = { title: "Campaign strategies" };

export default function Page() {
  return <StrategiesPage />;
}
