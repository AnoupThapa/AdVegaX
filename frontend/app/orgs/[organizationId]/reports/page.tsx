import type { Metadata } from "next";

import { ReportsPage } from "@/features/overview/ReportsPage";

export const metadata: Metadata = { title: "Reports" };

export default function Page() {
  return <ReportsPage />;
}
