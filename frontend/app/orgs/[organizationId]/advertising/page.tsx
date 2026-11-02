import type { Metadata } from "next";

import { AdAccountsPage } from "@/features/advertising/AdAccountsPage";

export const metadata: Metadata = { title: "Advertising" };

export default function Page() {
  return <AdAccountsPage />;
}
