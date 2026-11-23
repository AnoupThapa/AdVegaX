import type { Metadata } from "next";

import { OrganizationOverview } from "@/features/organizations/OrganizationOverview";

export const metadata: Metadata = { title: "Organization" };

export default function Page() {
  return <OrganizationOverview />;
}
