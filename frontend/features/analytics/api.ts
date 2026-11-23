"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type AnalyticsProperty = components["schemas"]["AnalyticsPropertyOut"];
export type AnalyticsMetrics = components["schemas"]["AnalyticsDailyMetricsOut"];
export type AnalyticsDay = components["schemas"]["AnalyticsDayOut"];
export type AnalyticsFigures = components["schemas"]["AnalyticsFiguresOut"];
export type AnalyticsItem = components["schemas"]["AnalyticsItemOut"];
export type AnalyticsQuality = components["schemas"]["AnalyticsQualityOut"];
export type Breakdown = "total" | "channel" | "source";

export const analyticsKeys = {
  properties: (org: string) => ["organization", org, "analytics-properties"] as const,
  property: (org: string, id: string) => ["organization", org, "analytics-properties", id] as const,
  metrics: (org: string, id: string, breakdown: Breakdown, from: string, to: string) =>
    ["organization", org, "analytics-properties", id, "metrics", breakdown, from, to] as const,
};

const SYNC_POLL_MS = 5000;

const propertyPath = (org: string, id: string) => ({ organization_id: org, property_id: id });

/** Analytics properties; re-checked every few seconds while any of them is updating. */
export function useAnalyticsProperties(orgId: string) {
  return useQuery({
    queryKey: analyticsKeys.properties(orgId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics-properties", {
          params: { path: { organization_id: orgId } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.some((p) => p.sync.running)
        ? SYNC_POLL_MS
        : false,
  });
}

export function useAnalyticsProperty(orgId: string, propertyId: string) {
  return useQuery({
    queryKey: analyticsKeys.property(orgId, propertyId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics-properties/{property_id}", {
          params: { path: propertyPath(orgId, propertyId) },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.sync.running ? SYNC_POLL_MS : false,
  });
}

export function useAnalyticsMetrics(
  orgId: string,
  propertyId: string,
  breakdown: Breakdown,
  from: string,
  to: string,
) {
  return useQuery({
    queryKey: analyticsKeys.metrics(orgId, propertyId, breakdown, from, to),
    queryFn: () =>
      unwrap(
        api.GET(
          "/api/v1/organizations/{organization_id}/analytics-properties/{property_id}/metrics/daily",
          { params: { path: propertyPath(orgId, propertyId), query: { from, to, breakdown } } },
        ),
      ),
  });
}

export function useAnalyticsResync(orgId: string, propertyId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST(
          "/api/v1/organizations/{organization_id}/analytics-properties/{property_id}/resync",
          { params: { path: propertyPath(orgId, propertyId) } },
        ),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: analyticsKeys.property(orgId, propertyId) }),
        queryClient.invalidateQueries({ queryKey: analyticsKeys.properties(orgId) }),
      ]),
  });
}
