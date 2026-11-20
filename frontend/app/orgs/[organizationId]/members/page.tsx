import type { Metadata } from "next";

import { MembersPage } from "@/features/organizations/MembersPage";

export const metadata: Metadata = { title: "Members" };

export default function Page() {
  return <MembersPage />;
}
