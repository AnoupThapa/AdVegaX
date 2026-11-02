import type { Metadata } from "next";
import { Suspense } from "react";

import { RequireAuth } from "@/features/auth/RequireAuth";
import { CreateOrganizationForm } from "@/features/organizations/CreateOrganizationForm";

export const metadata: Metadata = { title: "Create an organization" };

export default function Page() {
  return (
    <Suspense>
      <RequireAuth>
        <CreateOrganizationForm />
      </RequireAuth>
    </Suspense>
  );
}
