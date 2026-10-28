"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type AdminMe = components["schemas"]["AdminMeOut"];
export type AdminSetting = components["schemas"]["SettingOut"];

const keys = {
  me: ["admin", "me"] as const,
  settings: ["admin", "settings"] as const,
  organizations: ["admin", "organizations"] as const,
  users: ["admin", "users"] as const,
  health: ["admin", "health"] as const,
};

export function useAdminMe(enabled = true) {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => unwrap(api.GET("/api/v1/admin/me")),
    enabled,
  });
}

function useMe<T>(call: (vars: T) => Promise<AdminMe>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => {
      queryClient.setQueryData(keys.me, data);
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
    },
  });
}

export function useTwoStepSetup() {
  return useMutation({ mutationFn: () => unwrap(api.POST("/api/v1/admin/two-step/setup")) });
}

export function useTwoStepEnable() {
  return useMe((code: string) =>
    unwrap(api.POST("/api/v1/admin/two-step/enable", { body: { code } })),
  );
}

export function useTwoStepVerify() {
  return useMe((code: string) =>
    unwrap(api.POST("/api/v1/admin/two-step/verify", { body: { code } })),
  );
}

export function useAdminSettings(enabled: boolean) {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => unwrap(api.GET("/api/v1/admin/settings")),
    enabled,
  });
}

export function useSaveSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, value }: { name: string; value: string }) =>
      unwrap(
        api.PUT("/api/v1/admin/settings/{name}", {
          params: { path: { name } },
          body: { value },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(keys.settings, data);
      void queryClient.invalidateQueries({ queryKey: keys.health });
    },
  });
}

export function useClearSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      unwrap(api.DELETE("/api/v1/admin/settings/{name}", { params: { path: { name } } })),
    onSuccess: (data) => queryClient.setQueryData(keys.settings, data),
  });
}

export function useAdminOrganizations(enabled: boolean) {
  return useQuery({
    queryKey: keys.organizations,
    queryFn: () => unwrap(api.GET("/api/v1/admin/organizations")),
    enabled,
  });
}

export function useSetOrganizationStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "active" | "suspended" }) =>
      unwrap(
        api.PUT("/api/v1/admin/organizations/{organization_id}/status", {
          params: { path: { organization_id: id } },
          body: { status },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.organizations }),
  });
}

export function useAdminUsers(enabled: boolean) {
  return useQuery({
    queryKey: keys.users,
    queryFn: () => unwrap(api.GET("/api/v1/admin/users")),
    enabled,
  });
}

export function useAdminHealth(enabled: boolean) {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => unwrap(api.GET("/api/v1/admin/health")),
    enabled,
  });
}
