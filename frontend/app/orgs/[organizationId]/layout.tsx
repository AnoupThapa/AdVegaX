import type { ReactNode } from "react";
import { Suspense } from "react";

import { OrganizationShell } from "@/features/organizations/OrganizationShell";

export default function OrganizationLayout({ children }: { children: ReactNode }) {
  return (
    <Suspense>
      <OrganizationShell>{children}</OrganizationShell>
    </Suspense>
  );
}
