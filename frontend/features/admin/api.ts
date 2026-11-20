"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import { apiErrorFrom } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type AdminMe = components["schemas"]["AdminMeOut"];
export type AdminSetting = components["schemas"]["SettingOut"];

const keys = {
  me: ["admin", "me"] as const,
  settings: ["admin", "settings"] as const,
  organizations: ["admin", "organizations"] as const,
  users: ["admin", "users"] as const,
  organizationsPage: (q: OrganizationQuery) => ["admin", "organizations", q] as const,
  usersPage: (q: UserQuery) => ["admin", "users", q] as const,
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

export type OrganizationQuery = {
  readonly q: string;
  readonly status: "" | "active" | "suspended";
  readonly page: number;
};
export type UserQuery = {
  readonly q: string;
  readonly sort: "newest" | "email";
  readonly page: number;
};
export const ADMIN_PAGE_SIZE = 50;

/** A page of a list and how many there are in all (QA-011: searched and paged on the server). */
async function page<T>(
  call: Promise<{
    data?: { data: T[]; meta: { total: number } };
    error?: unknown;
    response: Response;
  }>,
): Promise<{ items: T[]; total: number }> {
  const result = await call;
  if (result.response.ok && result.data !== undefined) {
    return { items: result.data.data, total: result.data.meta.total };
  }
  throw apiErrorFrom(result.response.status, result.error, result.response.headers);
}

export function useAdminOrganizations(enabled: boolean, query: OrganizationQuery) {
  return useQuery({
    queryKey: keys.organizationsPage(query),
    queryFn: () =>
      page(
        api.GET("/api/v1/admin/organizations", {
          params: {
            query: {
              q: query.q,
              ...(query.status ? { status: query.status } : {}),
              page: query.page,
              page_size: ADMIN_PAGE_SIZE,
            },
          },
        }),
      ),
    enabled,
    placeholderData: keepPreviousData,
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
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.organizations }),
        queryClient.invalidateQueries({ queryKey: keys.health }),
      ]),
  });
}

export function useAdminUsers(enabled: boolean, query: UserQuery) {
  return useQuery({
    queryKey: keys.usersPage(query),
    queryFn: () =>
      page(
        api.GET("/api/v1/admin/users", {
          params: {
            query: { q: query.q, sort: query.sort, page: query.page, page_size: ADMIN_PAGE_SIZE },
          },
        }),
      ),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useAdminHealth(enabled: boolean) {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => unwrap(api.GET("/api/v1/admin/health")),
    enabled,
  });
}
