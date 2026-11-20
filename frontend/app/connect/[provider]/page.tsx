import type { Metadata } from "next";
import { Suspense } from "react";

import { RequireAuth } from "@/features/auth/RequireAuth";
import { InstallLanding } from "@/features/connections/InstallLanding";

export const metadata: Metadata = { title: "Connect a store" };

export default function Page() {
  return (
    <Suspense>
      <RequireAuth>
        <InstallLanding />
      </RequireAuth>
    </Suspense>
  );
}
