import type { Metadata } from "next";

import { ConnectionsPage } from "@/features/connections/ConnectionsPage";

export const metadata: Metadata = { title: "Connections" };

export default function Page() {
  return <ConnectionsPage />;
}
