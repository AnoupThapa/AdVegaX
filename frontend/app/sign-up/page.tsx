import type { Metadata } from "next";

import { SignUpForm } from "@/features/auth/SignUpForm";

export const metadata: Metadata = { title: "Create your account" };

export default function Page() {
  return <SignUpForm />;
}
