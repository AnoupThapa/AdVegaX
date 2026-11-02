import type { Metadata } from "next";
import { Suspense } from "react";

import { CampaignPage } from "@/features/advertising/CampaignPage";

export const metadata: Metadata = { title: "Campaign" };

export default function Page() {
  // The period comes from the address (useSearchParams), which needs a Suspense boundary.
  return (
    <Suspense>
      <CampaignPage />
    </Suspense>
  );
}
