import type { Metadata } from "next";
import { Suspense } from "react";

import { CallbackLanding } from "@/features/connections/CallbackLanding";

export const metadata: Metadata = { title: "Connecting a platform" };

export default function Page() {
  return (
    <Suspense>
      <CallbackLanding />
    </Suspense>
  );
}
