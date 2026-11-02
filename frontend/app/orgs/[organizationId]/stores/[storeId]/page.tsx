import type { Metadata } from "next";

import { StorePage } from "@/features/stores/StorePage";

export const metadata: Metadata = { title: "Store" };

export default function Page() {
  return <StorePage />;
}
