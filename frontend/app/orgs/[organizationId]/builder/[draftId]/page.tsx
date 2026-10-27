import type { Metadata } from "next";

import { DraftPage } from "@/features/builder/DraftPage";

export const metadata: Metadata = { title: "Campaign" };

export default function Page() {
  return <DraftPage />;
}
