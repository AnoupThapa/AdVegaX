import type { Metadata } from "next";

import { VerifyEmail } from "@/features/auth/VerifyEmail";

export const metadata: Metadata = { title: "Verify your email" };

export default function Page() {
  return <VerifyEmail />;
}
