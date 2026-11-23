"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SESSION_KEY } from "@/features/auth/session";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type DeviceSession = components["schemas"]["SessionOut"];

export const SESSIONS_KEY = ["auth-sessions"] as const;

export function useDeviceSessions() {
  return useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/auth/sessions")),
  });
}

export function useRevokeSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) =>
      unwrap(
        api.DELETE("/api/v1/auth/sessions/{session_id}", {
          params: { path: { session_id: sessionId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
}

/** Signs out every device, this one included. */
export function useSignOutEverywhere() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout-all")),
    onSuccess: () => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
      queryClient.setQueryData(SESSION_KEY, null);
    },
  });
}

/**
 * The API checks the current password, revokes every session and starts a new one for this
 * browser (the client picks up the new CSRF token from the response).
 */
export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      unwrap(api.POST("/api/v1/auth/change-password", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SESSIONS_KEY }),
  });
}
