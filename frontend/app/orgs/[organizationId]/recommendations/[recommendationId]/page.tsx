import type { Metadata } from "next";

import { RecommendationDetailPage } from "@/features/recommendations/RecommendationsPages";

export const metadata: Metadata = { title: "Recommendation" };

export default function Page() {
  return <RecommendationDetailPage />;
}
