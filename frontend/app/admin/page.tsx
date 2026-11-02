import type { Metadata } from "next";
import { Suspense } from "react";

import { AdminPage } from "@/features/admin/AdminPage";

export const metadata: Metadata = { title: "Admin" };

export default function Page() {
  return (
    <Suspense>
      <AdminPage />
    </Suspense>
  );
}
