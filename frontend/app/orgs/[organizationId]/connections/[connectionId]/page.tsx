import type { Metadata } from "next";

import { ConnectionDetailPage } from "@/features/connections/ConnectionDetailPage";

export const metadata: Metadata = { title: "Connection" };

export default function Page() {
  return <ConnectionDetailPage />;
}
