"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { handleSessionEnded } from "@/features/auth/session";
import { setUnauthenticatedHandler } from "@/lib/api";
import { createQueryClient } from "@/lib/query/query-client";

/** Client-side providers. Signed-in data lives only in this in-memory cache. */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient);

  useEffect(() => {
    // Session ended (401): drop signed-in data and mark the session as signed out, which sends
    // protected pages to sign-in (RequireAuth).
    setUnauthenticatedHandler(() => handleSessionEnded(queryClient));
    return () => setUnauthenticatedHandler(null);
  }, [queryClient]);

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
