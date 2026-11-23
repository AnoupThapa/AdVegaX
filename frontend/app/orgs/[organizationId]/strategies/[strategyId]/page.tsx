import type { Metadata } from "next";

import { StrategyDetail } from "@/features/strategies/StrategyDetail";

export const metadata: Metadata = { title: "Campaign strategy" };

export default function Page() {
  return <StrategyDetail />;
}
