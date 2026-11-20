"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Store = components["schemas"]["StoreOut"];
export type Product = components["schemas"]["ProductOut"];
export type Variant = components["schemas"]["VariantOut"];
export type DailyMetrics = components["schemas"]["DailyMetricsOut"];
export type Day = components["schemas"]["DayOut"];

export const storeKeys = {
  stores: (org: string) => ["organization", org, "stores"] as const,
  store: (org: string, id: string) => ["organization", org, "stores", id] as const,
  products: (org: string, id: string, q: string, status: string) =>
    ["organization", org, "stores", id, "products", q, status] as const,
  metrics: (org: string, id: string, from: string, to: string) =>
    ["organization", org, "stores", id, "metrics", from, to] as const,
};

const SYNC_POLL_MS = 5000;

const path = (org: string, store: string) => ({ organization_id: org, store_id: store });

/** Stores; re-checked every few seconds while any of them is importing or syncing. */
export function useStores(orgId: string) {
  return useQuery({
    queryKey: storeKeys.stores(orgId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/stores", {
          params: { path: { organization_id: orgId } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.some((s) => s.sync.running)
        ? SYNC_POLL_MS
        : false,
  });
}

export function useStore(orgId: string, storeId: string) {
  return useQuery({
    queryKey: storeKeys.store(orgId, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/stores/{store_id}", {
          params: { path: path(orgId, storeId) },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.sync.running ? SYNC_POLL_MS : false,
  });
}

export function useProducts(orgId: string, storeId: string, q: string, status: string) {
  return useInfiniteQuery({
    queryKey: storeKeys.products(orgId, storeId, q, status),
    enabled: Boolean(storeId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/stores/{store_id}/products", {
          params: {
            path: path(orgId, storeId),
            query: {
              page_size: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
              ...(q ? { q } : {}),
              ...(status ? { status } : {}),
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
}

export function useDailyMetrics(orgId: string, storeId: string, from: string, to: string) {
  return useQuery({
    queryKey: storeKeys.metrics(orgId, storeId, from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/stores/{store_id}/metrics/daily", {
          params: { path: path(orgId, storeId), query: { from, to } },
        }),
      ),
  });
}

export function useResync(orgId: string, storeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/organizations/{organization_id}/stores/{store_id}/resync", {
          params: { path: path(orgId, storeId) },
        }),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: storeKeys.store(orgId, storeId) }),
        queryClient.invalidateQueries({ queryKey: storeKeys.stores(orgId) }),
      ]),
  });
}
