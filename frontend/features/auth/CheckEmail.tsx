import Link from "next/link";

import { PageCard } from "@/components/ui/PageCard";

export function CheckEmail() {
  return (
    <PageCard title="Check your email" footer={<Link href="/sign-in">Go to sign in</Link>}>
      <p>
        We&apos;ve sent a link to the address you entered. Open it on this device to verify your
        email. The link can be used once.
      </p>
      <p>Nothing arrived? Check your spam folder. After signing in you can ask for a new link.</p>
    </PageCard>
  );
}
