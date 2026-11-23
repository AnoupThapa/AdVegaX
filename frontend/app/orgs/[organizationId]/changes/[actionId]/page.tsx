import type { Metadata } from "next";

import { ChangeDetailPage } from "@/features/changes/ChangesPages";

export const metadata: Metadata = { title: "Change" };

export default function Page() {
  return <ChangeDetailPage />;
}
