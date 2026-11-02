/** Server-state cache defaults (PHASE_01C_PLAN §4.5). Mutations never retry automatically. */

import { QueryClient } from "@tanstack/react-query";

import { ApiError, NETWORK_ERROR } from "@/lib/api/errors";

const MAX_QUERY_RETRIES = 2;

/** Retry reads only for network failures and server errors (5xx) — never for 4xx answers. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  if (!(error instanceof ApiError)) return false;
  return error.code === NETWORK_ERROR || error.status >= 500;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: shouldRetryQuery,
        refetchOnWindowFocus: true,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
