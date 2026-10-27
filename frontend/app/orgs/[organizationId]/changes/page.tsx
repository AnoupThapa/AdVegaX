import type { Metadata } from "next";

import { ChangesPage } from "@/features/changes/ChangesPages";

export const metadata: Metadata = { title: "Changes" };

export default function Page() {
  return <ChangesPage />;
}
