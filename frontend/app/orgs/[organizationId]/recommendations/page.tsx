import type { Metadata } from "next";

import { RecommendationsPage } from "@/features/recommendations/RecommendationsPages";

export const metadata: Metadata = { title: "Recommendations" };

export default function Page() {
  return <RecommendationsPage />;
}
