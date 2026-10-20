"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adKeys } from "@/features/advertising/api";
import { analyticsKeys } from "@/features/analytics/api";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Overview = components["schemas"]["OverviewOut"];
export type OverviewDay = components["schemas"]["OverviewDayOut"];
export type MetricDefinition = components["schemas"]["MetricDefinitionOut"];
export type Source = components["schemas"]["SourceOut"];
export type Conversion = components["schemas"]["ConversionOut"];

/** Every unified-analytics answer of an organization starts with this key (6-07, 6-08). */
export const unifiedKeys = {
  all: (org: string) => ["organization", org, "unified-analytics"] as const,
  overview: (org: string, from: string, to: string, store: string | null) =>
    ["organization", org, "unified-analytics", "overview", from, to, store] as const,
};

/** Sales, ad spend and profit together for a period (GET /analytics/overview). */
export function useOverview(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: unifiedKeys.overview(orgId, from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/overview", {
          params: {
            path: { organization_id: orgId },
            query: { from, to, ...(storeId ? { store_id: storeId } : {}) },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export type AssignmentKind = "ad_account" | "analytics_property";

/** Which store an ad account or Google Analytics property belongs to (Q-6-1); null = all. */
export function useAssignStore(orgId: string, kind: AssignmentKind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, storeId }: { id: string; storeId: string | null }): Promise<void> => {
      await (kind === "ad_account"
        ? unwrap(
            api.PUT("/api/v1/organizations/{organization_id}/ad-accounts/{ad_account_id}/store", {
              params: { path: { organization_id: orgId, ad_account_id: id } },
              body: { store_id: storeId },
            }),
          )
        : unwrap(
            api.PUT(
              "/api/v1/organizations/{organization_id}/analytics-properties/{property_id}/store",
              {
                params: { path: { organization_id: orgId, property_id: id } },
                body: { store_id: storeId },
              },
            ),
          ));
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey:
            kind === "ad_account" ? adKeys.accounts(orgId) : analyticsKeys.properties(orgId),
        }),
        queryClient.invalidateQueries({ queryKey: unifiedKeys.all(orgId) }),
      ]),
  });
}
