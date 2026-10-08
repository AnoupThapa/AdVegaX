"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";

import { SESSION_KEY, fetchSession } from "./session";

export function useSignUp() {
  return useMutation({
    mutationFn: (body: { email: string; password: string; display_name?: string | null }) =>
      unwrap(api.POST("/api/v1/auth/register", { body })),
  });
}

export function useSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      unwrap(api.POST("/api/v1/auth/login", { body })),
    onSuccess: async () => {
      // A new session: forget anything cached for a previous user, then load this one.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
      queryClient.setQueryData(SESSION_KEY, await fetchSession());
    },
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    onSettled: () => {
      // Even if the request failed, clear local data: never keep signed-in data on screen.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
      queryClient.setQueryData(SESSION_KEY, null);
    },
  });
}

export function useVerifyEmail() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      unwrap(api.POST("/api/v1/auth/verify-email", { body: { token } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SESSION_KEY }),
  });
}

export function useResendVerification() {
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/resend-verification")),
  });
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (email: string) =>
      unwrap(api.POST("/api/v1/auth/forgot-password", { body: { email } })),
  });
}

export function useResetPassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { token: string; new_password: string }) =>
      unwrap(api.POST("/api/v1/auth/reset-password", { body })),
    // The API revokes every session on reset: treat this browser as signed out.
    onSuccess: () => {
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== SESSION_KEY[0] });
      queryClient.setQueryData(SESSION_KEY, null);
    },
  });
}
