"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { unifiedKeys } from "@/features/overview/api";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Funnel = components["schemas"]["FunnelOut"];
export type FunnelStep = components["schemas"]["StepOut"];
export type FunnelFinding = components["schemas"]["FindingOut"];
export type CampaignFunnels = components["schemas"]["CampaignFunnelsOut"];
export type LandingPages = components["schemas"]["LandingPagesOut"];

const query = (from: string, to: string, storeId: string | null) => ({
  from,
  to,
  ...(storeId ? { store_id: storeId } : {}),
});

const key = (org: string, part: string, from: string, to: string, store: string | null) =>
  [...unifiedKeys.all(org), "funnel", part, from, to, store] as const;

/** Impression → purchase with sources, steps, platforms, channels and findings. */
export function useFunnel(orgId: string, from: string, to: string, storeId: string | null) {
  return useQuery({
    queryKey: key(orgId, "whole", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/funnel", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useCampaignFunnels(
  orgId: string,
  from: string,
  to: string,
  storeId: string | null,
) {
  return useQuery({
    queryKey: key(orgId, "campaigns", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/funnel/campaigns", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useLandingPageFunnels(
  orgId: string,
  from: string,
  to: string,
  storeId: string | null,
) {
  return useQuery({
    queryKey: key(orgId, "landing-pages", from, to, storeId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/analytics/funnel/landing-pages", {
          params: { path: { organization_id: orgId }, query: query(from, to, storeId) },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}
