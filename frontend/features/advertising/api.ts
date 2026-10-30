"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type AdAccount = components["schemas"]["AdAccountOut"];
export type AdDailyMetrics = components["schemas"]["AdDailyMetricsOut"];
export type AdDay = components["schemas"]["AdDayOut"];
export type AdFigures = components["schemas"]["AdFiguresOut"];
export type AdCampaign = components["schemas"]["AdCampaignOut"];
export type AdCampaignList = components["schemas"]["AdCampaignListOut"];
export type AdCampaignDetail = components["schemas"]["AdCampaignDetailOut"];
export type AdBudget = components["schemas"]["AdBudgetOut"];

export const adKeys = {
  accounts: (org: string) => ["organization", org, "ad-accounts"] as const,
  account: (org: string, id: string) => ["organization", org, "ad-accounts", id] as const,
  metrics: (org: string, id: string, from: string, to: string) =>
    ["organization", org, "ad-accounts", id, "metrics", from, to] as const,
  campaigns: (org: string, id: string, from: string, to: string) =>
    ["organization", org, "ad-accounts", id, "campaigns", from, to] as const,
  campaign: (org: string, id: string, from: string | null, to: string | null) =>
    ["organization", org, "campaigns", id, from, to] as const,
};

const SYNC_POLL_MS = 5000;

const accountPath = (org: string, id: string) => ({ organization_id: org, ad_account_id: id });

/** Ad accounts; re-checked every few seconds while any of them is importing or updating. */
export function useAdAccounts(orgId: string) {
  return useQuery({
    queryKey: adKeys.accounts(orgId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/ad-accounts", {
          params: { path: { organization_id: orgId } },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.some((a) => a.sync.running)
        ? SYNC_POLL_MS
        : false,
  });
}

export function useAdAccount(orgId: string, accountId: string) {
  return useQuery({
    queryKey: adKeys.account(orgId, accountId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/ad-accounts/{ad_account_id}", {
          params: { path: accountPath(orgId, accountId) },
        }),
      ),
    refetchInterval: (query) =>
      query.state.status !== "error" && query.state.data?.sync.running ? SYNC_POLL_MS : false,
  });
}

export function useAdDailyMetrics(orgId: string, accountId: string, from: string, to: string) {
  return useQuery({
    queryKey: adKeys.metrics(orgId, accountId, from, to),
    queryFn: () =>
      unwrap(
        api.GET(
          "/api/v1/organizations/{organization_id}/ad-accounts/{ad_account_id}/metrics/daily",
          { params: { path: accountPath(orgId, accountId), query: { from, to } } },
        ),
      ),
  });
}

export function useAdCampaigns(orgId: string, accountId: string, from: string, to: string) {
  return useQuery({
    queryKey: adKeys.campaigns(orgId, accountId, from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/ad-accounts/{ad_account_id}/campaigns", {
          params: { path: accountPath(orgId, accountId), query: { from, to } },
        }),
      ),
  });
}

/** One campaign; without a period the API answers for the account's last 30 days. */
export function useAdCampaign(
  orgId: string,
  campaignId: string,
  from: string | null,
  to: string | null,
) {
  return useQuery({
    queryKey: adKeys.campaign(orgId, campaignId, from, to),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/campaigns/{campaign_id}", {
          params: {
            path: { organization_id: orgId, campaign_id: campaignId },
            query: from && to ? { from, to } : {},
          },
        }),
      ),
  });
}

export function useAdResync(orgId: string, accountId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/organizations/{organization_id}/ad-accounts/{ad_account_id}/resync", {
          params: { path: accountPath(orgId, accountId) },
        }),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: adKeys.account(orgId, accountId) }),
        queryClient.invalidateQueries({ queryKey: adKeys.accounts(orgId) }),
      ]),
  });
}
