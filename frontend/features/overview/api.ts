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
export type Channels = components["schemas"]["ChannelsOut"];
export type Campaigns = components["schemas"]["CampaignsOut"];
export type Campaign = components["schemas"]["CampaignOut"];
export type Products = components["schemas"]["ProductsOut"];
export type ProductFigures = components["schemas"]["ProductFiguresOut"];
export type Report = "channels" | "campaigns" | "products";

/** Every unified-analytics answer of an organization starts with this key (6-07, 6-08). */
export const unifiedKeys = {
  all: (org: string) => ["organization", org, "unified-analytics"] as const,
  overview: (org: string, from: string, to: string, store: string | null) =>
    ["organization", org, "unified-analytics", "overview", from, to, store] as const,
  report: (org: string, report: Report, from: string, to: string, store: string | null) =>
    ["organization", org, "unified-analytics", report, from, to, store] as const,
};

const query = (from: string, to: string, storeId: string | null) => ({
  from,
  to,
  ...(storeId ? { store_id: storeId } : {}),
});

/** Sales, ad spend and profit together for a period (GET /analytics/overview). */
export function useOverview(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: unifiedKeys.overview(orgId, from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/overview", {
          params: {
            path: { organization_id: orgId },
            query: query(from, to, storeId),
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** Each ad platform's own figures and Google Analytics' channels (GET /analytics/channels). */
export function useChannels(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: unifiedKeys.report(orgId, "channels", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/channels", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** Every campaign with its platform figures and Google Analytics match. */
export function useCampaigns(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: unifiedKeys.report(orgId, "campaigns", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/campaigns", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/** Every product sold in the period with units, sales, cost and margin. */
export function useProductFigures(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: unifiedKeys.report(orgId, "products", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/products", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
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
