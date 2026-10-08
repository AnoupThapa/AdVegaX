import type { Metadata } from "next";

import { CheckEmail } from "@/features/auth/CheckEmail";

export const metadata: Metadata = { title: "Check your email" };

export default function Page() {
  return <CheckEmail />;
}
