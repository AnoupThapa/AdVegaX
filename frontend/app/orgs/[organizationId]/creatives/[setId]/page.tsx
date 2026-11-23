import type { Metadata } from "next";

import { CreativeSetPage } from "@/features/creatives/CreativesPages";

export const metadata: Metadata = { title: "Creatives for a strategy" };

export default function Page() {
  return <CreativeSetPage />;
}
