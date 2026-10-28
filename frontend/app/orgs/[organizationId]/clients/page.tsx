import type { Metadata } from "next";

import { ClientsPage } from "@/features/agency/ClientsPage";

export const metadata: Metadata = { title: "Clients" };

export default function Page() {
  return <ClientsPage />;
}
