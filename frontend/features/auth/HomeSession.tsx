"use client";

import Link from "next/link";

import { useSession } from "./session";
import { UnverifiedNotice } from "./UnverifiedNotice";

/** The signed-in or signed-out part of the home page. */
export function HomeSession() {
  const { user } = useSession();
  if (user === undefined) return null;
  if (user === null) {
    return (
      <p>
        <Link href="/sign-up">Create an account</Link> or <Link href="/sign-in">sign in</Link> to
        get started.
      </p>
    );
  }
  return (
    <div>
      <p>
        You are signed in as <strong>{user.display_name || user.email}</strong>.
      </p>
      <UnverifiedNotice user={user} />
    </div>
  );
}
