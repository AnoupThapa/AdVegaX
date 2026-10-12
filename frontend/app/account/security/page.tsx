import type { Metadata } from "next";
import { Suspense } from "react";

import { AccountSecurityPage } from "@/features/account/AccountSecurityPage";

export const metadata: Metadata = { title: "Account security" };

export default function Page() {
  return (
    <Suspense>
      <AccountSecurityPage />
    </Suspense>
  );
}
