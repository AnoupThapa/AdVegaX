"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Strategy = components["schemas"]["StrategyOut"];
export type StrategySummary = components["schemas"]["StrategySummaryOut"];
export type StrategyCreate = components["schemas"]["StrategyCreateIn"];
export type StrategyUpdate = components["schemas"]["StrategyUpdateIn"];
export type Evidence = components["schemas"]["EvidenceOut"];
export type AiUsage = components["schemas"]["UsageOut"];
export type UsagePeriod = components["schemas"]["UsagePeriodOut"];

/** The strategy object as the planner writes it (API_SPECIFICATION §19H). */
export type PlanPlatform = {
  platform: string;
  campaign_type: string;
  budget_share_percent: number;
  audience: string;
  reasoning: string;
  evidence: string[];
};
export type Plan = {
  objective: string;
  summary: string;
  positioning: string;
  platforms: PlanPlatform[];
  angles: Array<{ angle: string; evidence: string[] }>;
  targets: Array<{ metric: string; low: number; high: number; evidence: string[] }>;
  risks: Array<{ code: string; text: string }>;
  assumptions: string[];
};

export const asPlan = (strategy: Strategy): Plan => strategy.strategy as unknown as Plan;

export const strategyKeys = {
  all: (org: string) => ["organization", org, "strategies"] as const,
  lists: (org: string) => ["organization", org, "strategies", "list"] as const,
  list: (org: string, status: string) =>
    ["organization", org, "strategies", "list", status] as const,
  one: (org: string, id: string) => ["organization", org, "strategies", "one", id] as const,
  usage: (org: string) => ["organization", org, "ai-usage"] as const,
};

const BASE = "/api/v1/organizations/{organization_id}/ai/campaign-strategies" as const;
const ONE = "/api/v1/organizations/{organization_id}/ai/campaign-strategies/{strategy_id}" as const;

/** Strategies, most recently changed first. "" = everything but archived. */
export function useStrategies(orgId: string, status: "" | "draft" | "ready" | "archived") {
  return useQuery({
    queryKey: strategyKeys.list(orgId, status),
    queryFn: () =>
      unwrap(
        api.GET(BASE, {
          params: {
            path: { organization_id: orgId },
            query: { page_size: 100, ...(status ? { status } : {}) },
          },
        }),
      ),
  });
}

export function useStrategy(orgId: string, strategyId: string) {
  return useQuery({
    queryKey: strategyKeys.one(orgId, strategyId),
    queryFn: () =>
      unwrap(
        api.GET(ONE, {
          params: { path: { organization_id: orgId, strategy_id: strategyId } },
        }),
      ),
  });
}

export function useGenerateStrategy(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StrategyCreate) =>
      unwrap(api.POST(BASE, { params: { path: { organization_id: orgId } }, body })),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: strategyKeys.all(orgId) }),
        queryClient.invalidateQueries({ queryKey: strategyKeys.usage(orgId) }),
      ]),
  });
}

function useStrategyChange<T>(
  orgId: string,
  strategyId: string,
  call: (body: T) => ReturnType<typeof unwrap<{ data: Strategy }>>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => queryClient.setQueryData(strategyKeys.one(orgId, strategyId), data),
    // The answer is the strategy as saved; only the lists need reading again.
    onSettled: () => queryClient.invalidateQueries({ queryKey: strategyKeys.lists(orgId) }),
  });
}

export function useUpdateStrategy(orgId: string, strategyId: string) {
  const path = { organization_id: orgId, strategy_id: strategyId };
  return useStrategyChange(orgId, strategyId, (body: StrategyUpdate) =>
    unwrap(api.PATCH(ONE, { params: { path }, body })),
  );
}

export function useMarkReady(orgId: string, strategyId: string) {
  const path = { organization_id: orgId, strategy_id: strategyId };
  return useStrategyChange(orgId, strategyId, () =>
    unwrap(api.POST(`${ONE}/ready`, { params: { path } })),
  );
}

export function useArchive(orgId: string, strategyId: string) {
  const path = { organization_id: orgId, strategy_id: strategyId };
  return useStrategyChange(orgId, strategyId, () =>
    unwrap(api.POST(`${ONE}/archive`, { params: { path } })),
  );
}

/** AI runs, tokens and estimated cost (owners and admins). */
export function useAiUsage(orgId: string, enabled: boolean) {
  return useQuery({
    queryKey: strategyKeys.usage(orgId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/ai/usage", {
          params: { path: { organization_id: orgId } },
        }),
      ),
  });
}
