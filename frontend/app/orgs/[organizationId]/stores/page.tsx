import type { Metadata } from "next";

import { StoresPage } from "@/features/stores/StoresPage";

export const metadata: Metadata = { title: "Stores" };

export default function Page() {
  return <StoresPage />;
}
