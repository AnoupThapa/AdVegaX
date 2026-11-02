import type { Metadata } from "next";

import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";

export const metadata: Metadata = { title: "Organization settings" };

export default function Page() {
  return <OrganizationSettings />;
}
