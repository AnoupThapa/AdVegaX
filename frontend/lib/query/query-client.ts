/** Server-state cache defaults (PHASE_01C_PLAN §4.5). Mutations never retry automatically. */

import { QueryClient } from "@tanstack/react-query";

import { ApiError, NETWORK_ERROR } from "@/lib/api/errors";

const MAX_QUERY_RETRIES = 2;
// Unreachable is usually not a blip: say so after one quick retry instead of waiting through
// several (QA-015). Pages read again on their own when the window regains focus or reconnects.
const MAX_NETWORK_RETRIES = 1;

/** Retry reads only for network failures and server errors (5xx) — never for 4xx answers. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.code === NETWORK_ERROR) return failureCount < MAX_NETWORK_RETRIES;
  return failureCount < MAX_QUERY_RETRIES && error.status >= 500;
}

/** Short waits between retries: 0.5 s, then 1 s (at most 2 s). */
export function queryRetryDelay(attempt: number): number {
  return Math.min(500 * 2 ** attempt, 2_000);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: shouldRetryQuery,
        retryDelay: queryRetryDelay,
        refetchOnWindowFocus: true,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
