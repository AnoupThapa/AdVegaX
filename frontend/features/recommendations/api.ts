"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { changeKeys } from "@/features/changes/api";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Recommendation = components["schemas"]["RecommendationOut"];
export type RecommendationList = components["schemas"]["RecommendationListOut"];
export type OptimizationSettings = components["schemas"]["OptimizationSettingsOut"];
export type OptimizationSettingsIn = components["schemas"]["OptimizationSettingsIn"];
export type RejectReason = components["schemas"]["RecommendationRejectIn"]["reason"];

export const recommendationKeys = {
  all: (org: string) => ["organization", org, "recommendations"] as const,
  list: (org: string, status: string, campaign: string) =>
    ["organization", org, "recommendations", "list", status, campaign] as const,
  one: (org: string, id: string) => ["organization", org, "recommendations", "one", id] as const,
  settings: (org: string) => ["organization", org, "optimization-settings"] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const ONE = `${ORG}/recommendations/{recommendation_id}` as const;
const path = (orgId: string, id: string) => ({
  params: { path: { organization_id: orgId, recommendation_id: id } },
});

export function useRecommendations(orgId: string, status = "", campaignId = "") {
  return useQuery({
    queryKey: recommendationKeys.list(orgId, status, campaignId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/recommendations`, {
          params: {
            path: { organization_id: orgId },
            query: {
              ...(status ? { status: status as never } : {}),
              ...(campaignId ? { campaign_id: campaignId } : {}),
            },
          },
        }),
      ),
  });
}

export function useRecommendation(orgId: string, id: string) {
  return useQuery({
    queryKey: recommendationKeys.one(orgId, id),
    queryFn: () => unwrap(api.GET(ONE, path(orgId, id))),
  });
}

function useDecision<T>(orgId: string, call: (vars: T) => Promise<Recommendation>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: recommendationKeys.all(orgId) }),
        queryClient.invalidateQueries({ queryKey: changeKeys.all(orgId) }),
      ]),
  });
}

export function useApproveRecommendation(orgId: string) {
  return useDecision(orgId, (id: string) => unwrap(api.POST(`${ONE}/approve`, path(orgId, id))));
}

export function useRejectRecommendation(orgId: string) {
  return useDecision(orgId, (vars: { id: string; reason: RejectReason; note: string }) =>
    unwrap(
      api.POST(`${ONE}/reject`, {
        ...path(orgId, vars.id),
        body: { reason: vars.reason, note: vars.note.trim() || null },
      }),
    ),
  );
}

export function useRecommendationDone(orgId: string) {
  return useDecision(orgId, (id: string) => unwrap(api.POST(`${ONE}/done`, path(orgId, id))));
}

export function useRefreshRecommendations(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST(`${ORG}/recommendations/refresh`, {
          params: { path: { organization_id: orgId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: recommendationKeys.all(orgId) }),
  });
}

export function useOptimizationSettings(orgId: string) {
  return useQuery({
    queryKey: recommendationKeys.settings(orgId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/optimization-settings`, { params: { path: { organization_id: orgId } } }),
      ),
  });
}

export function useSaveOptimizationSettings(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OptimizationSettingsIn) =>
      unwrap(
        api.PUT(`${ORG}/optimization-settings`, {
          params: { path: { organization_id: orgId } },
          body,
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(recommendationKeys.settings(orgId), data),
  });
}
