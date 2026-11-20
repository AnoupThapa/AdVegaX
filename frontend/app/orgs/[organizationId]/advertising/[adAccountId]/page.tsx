import type { Metadata } from "next";

import { AdAccountPage } from "@/features/advertising/AdAccountPage";

export const metadata: Metadata = { title: "Ad account" };

export default function Page() {
  return <AdAccountPage />;
}
