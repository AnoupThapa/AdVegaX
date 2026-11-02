import type { Metadata } from "next";

import { AcceptInvitation } from "@/features/organizations/AcceptInvitation";

export const metadata: Metadata = { title: "Join an organization" };

export default function Page() {
  return <AcceptInvitation />;
}
