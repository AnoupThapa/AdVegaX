import type { Metadata } from "next";

import { FunnelPage } from "@/features/funnel/FunnelPage";

export const metadata: Metadata = { title: "Funnel" };

export default function Page() {
  return <FunnelPage />;
}
