"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { OrganizationSwitcher } from "@/features/organizations/OrganizationSwitcher";

import { AccountMenu } from "./AccountMenu";
import { useSignOut } from "./actions";
import styles from "./AccountNav.module.css";
import { useSession } from "./session";

export function AccountNav() {
  const { user } = useSession();
  const signOut = useSignOut();
  const router = useRouter();

  if (user === undefined) return null; // still loading: avoid flashing the wrong links

  if (user === null) {
    return (
      <nav aria-label="Account" className={styles.nav}>
        <Link href="/sign-in">Sign in</Link>
        <Link href="/sign-up" className={styles.primaryLink}>
          Create account
        </Link>
      </nav>
    );
  }

  return (
    <nav aria-label="Account" className={styles.nav}>
      <OrganizationSwitcher user={user} />
      <AccountMenu user={user} />
      <Button
        variant="secondary"
        busy={signOut.isPending}
        onClick={() => signOut.mutate(undefined, { onSettled: () => router.push("/sign-in") })}
      >
        Sign out
      </Button>
    </nav>
  );
}
