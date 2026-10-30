"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { messageFor } from "@/lib/api/errors";

import { takeDeliberateSignOut, useSession } from "./session";

/**
 * Wraps pages that need a signed-in user. Signed-out visitors — including anyone whose session
 * ends while on the page (401) — are sent to sign in and brought back afterwards. After a
 * deliberate "Sign out" they go to a plain sign-in page instead.
 * This is for usability only: the API refuses every request without a valid session.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, error } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();

  useEffect(() => {
    if (user === null) {
      if (takeDeliberateSignOut()) {
        router.replace("/sign-in");
        return;
      }
      const query = search.toString();
      const here = query ? `${pathname}?${query}` : pathname;
      router.replace(`/sign-in?next=${encodeURIComponent(here)}`);
    }
  }, [user, pathname, search, router]);

  if (user) return <>{children}</>;
  if (error) return <Alert tone="error">{messageFor(error)}</Alert>;
  return <p role="status">Loading…</p>;
}
