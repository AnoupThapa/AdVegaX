"use client";

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type SessionUser = components["schemas"]["UserOut"];

/** Cache key of the signed-in user. `null` means "signed out" (not "unknown"). */
export const SESSION_KEY = ["session"] as const;

export async function fetchSession(): Promise<SessionUser | null> {
  try {
    return await unwrap(api.GET("/api/v1/auth/me"));
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/** The current user, `null` when signed out, `undefined` while loading. */
export function useSession() {
  const query = useQuery({ queryKey: SESSION_KEY, queryFn: fetchSession });
  return { user: query.data, isLoading: query.isPending, error: query.error };
}

// Set when the person presses "Sign out" (kept in memory only). A protected page that is still
// open then sends them to a plain sign-in page instead of offering to come back to it, so the
// next person to sign in on this browser is not sent to the previous person's page.
let deliberateSignOut = false;

export function noteDeliberateSignOut(): void {
  deliberateSignOut = true;
}

/** True once after a deliberate sign-out; reading it clears it. */
export function takeDeliberateSignOut(): boolean {
  const value = deliberateSignOut;
  deliberateSignOut = false;
  return value;
}

/**
 * Called when the API answers 401: a previously signed-in session has ended.
 * Drops every cached response except the session itself, which becomes `null`, so protected
 * pages redirect to sign-in. A no-op when already signed out (prevents refetch loops).
 */
export function handleSessionEnded(queryClient: QueryClient): void {
  if (!queryClient.getQueryData(SESSION_KEY)) return;
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
  queryClient.setQueryData(SESSION_KEY, null);
}
