"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type AutopilotPolicy = components["schemas"]["AutopilotPolicyOut"];
export type AutopilotPolicyIn = components["schemas"]["AutopilotPolicyIn"];
export type AutopilotRun = components["schemas"]["AutopilotRunOut"];

export const autopilotKeys = {
  policy: (org: string) => ["organization", org, "autopilot"] as const,
  runs: (org: string) => ["organization", org, "autopilot", "runs"] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const path = (orgId: string) => ({ params: { path: { organization_id: orgId } } });

export function useAutopilot(orgId: string) {
  return useQuery({
    queryKey: autopilotKeys.policy(orgId),
    queryFn: () => unwrap(api.GET(`${ORG}/autopilot`, path(orgId))),
  });
}

export function useAutopilotRuns(orgId: string) {
  return useQuery({
    queryKey: autopilotKeys.runs(orgId),
    queryFn: () => unwrap(api.GET(`${ORG}/autopilot/runs`, path(orgId))),
  });
}

function useChange<T>(orgId: string, call: (vars: T) => Promise<AutopilotPolicy>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: (data) => queryClient.setQueryData(autopilotKeys.policy(orgId), data),
  });
}

export function useSaveAutopilot(orgId: string) {
  return useChange(orgId, (body: AutopilotPolicyIn) =>
    unwrap(api.PUT(`${ORG}/autopilot`, { ...path(orgId), body })),
  );
}

export function useEnableAutopilot(orgId: string) {
  return useChange(orgId, (confirm: string) =>
    unwrap(api.POST(`${ORG}/autopilot/enable`, { ...path(orgId), body: { confirm } })),
  );
}

export function useStopAutopilot(orgId: string) {
  return useChange(orgId, () => unwrap(api.POST(`${ORG}/autopilot/stop`, path(orgId))));
}
