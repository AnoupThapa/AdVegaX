"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Action = components["schemas"]["ActionOut"];
export type ActionPreview = components["schemas"]["ActionPreviewOut"];
export type ActionCheck = components["schemas"]["ActionCheckOut"];
export type ActionSettings = components["schemas"]["ActionSettingsOut"];
export type WriteAccess = components["schemas"]["WriteAccessOut"];
export type ActionRequest = components["schemas"]["ActionIn"];
export type ActionType = ActionRequest["action_type"];

export const changeKeys = {
  all: (org: string) => ["organization", org, "changes"] as const,
  list: (org: string, status: string, campaign: string) =>
    ["organization", org, "changes", "list", status, campaign] as const,
  one: (org: string, id: string) => ["organization", org, "changes", "one", id] as const,
  settings: (org: string) => ["organization", org, "change-settings"] as const,
  access: (org: string, connection: string) =>
    ["organization", org, "write-access", connection] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const ONE = `${ORG}/actions/{action_id}` as const;
// Changes still on their way are read again every few seconds, until they are done.
const MOVING = new Set(["approved", "queued", "submitting", "unknown"]);

export function useActions(orgId: string, status: string, campaignId = "") {
  return useQuery({
    queryKey: changeKeys.list(orgId, status, campaignId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/actions`, {
          params: {
            path: { organization_id: orgId },
            query: {
              ...(status ? { status: status as never } : {}),
              ...(campaignId ? { campaign_id: campaignId } : {}),
              page_size: 50,
            },
          },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.some((a) => MOVING.has(a.status)) ? 3000 : false,
  });
}

export function useAction(orgId: string, actionId: string) {
  return useQuery({
    queryKey: changeKeys.one(orgId, actionId),
    queryFn: () =>
      unwrap(api.GET(ONE, { params: { path: { organization_id: orgId, action_id: actionId } } })),
    refetchInterval: (query) => (MOVING.has(query.state.data?.status ?? "") ? 3000 : false),
  });
}

export function useValidateChange(orgId: string) {
  return useMutation({
    mutationFn: (body: ActionRequest) =>
      unwrap(
        api.POST(`${ORG}/actions/validate`, { params: { path: { organization_id: orgId } }, body }),
      ),
  });
}

export function useRequestChange(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ActionRequest) =>
      unwrap(api.POST(`${ORG}/actions`, { params: { path: { organization_id: orgId } }, body })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: changeKeys.all(orgId) }),
  });
}

function useDecision<T>(orgId: string, call: (vars: T) => Promise<Action>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: changeKeys.all(orgId) }),
        // A change that was made shows on the campaign at once.
        queryClient.invalidateQueries({ queryKey: ["organization", orgId, "campaigns"] }),
        queryClient.invalidateQueries({ queryKey: ["organization", orgId, "ad-accounts"] }),
      ]),
  });
}

const path = (orgId: string, id: string) => ({
  params: { path: { organization_id: orgId, action_id: id } },
});

export function useApproveChange(orgId: string) {
  return useDecision(orgId, (id: string) => unwrap(api.POST(`${ONE}/approve`, path(orgId, id))));
}

export function useRejectChange(orgId: string) {
  return useDecision(orgId, (vars: { id: string; reason: string }) =>
    unwrap(api.POST(`${ONE}/reject`, { ...path(orgId, vars.id), body: { reason: vars.reason } })),
  );
}

export function useCancelChange(orgId: string) {
  return useDecision(orgId, (id: string) => unwrap(api.POST(`${ONE}/cancel`, path(orgId, id))));
}

export function useUndoChange(orgId: string) {
  return useDecision(orgId, (id: string) => unwrap(api.POST(`${ONE}/undo`, path(orgId, id))));
}

export function useChangeSettings(orgId: string) {
  return useQuery({
    queryKey: changeKeys.settings(orgId),
    queryFn: () =>
      unwrap(api.GET(`${ORG}/action-settings`, { params: { path: { organization_id: orgId } } })),
  });
}

export function useSaveChangeSettings(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: components["schemas"]["ActionSettingsIn"]) =>
      unwrap(
        api.PUT(`${ORG}/action-settings`, { params: { path: { organization_id: orgId } }, body }),
      ),
    onSuccess: (data) => queryClient.setQueryData(changeKeys.settings(orgId), data),
    onSettled: () => queryClient.invalidateQueries({ queryKey: changeKeys.all(orgId) }),
  });
}

export function useWriteAccess(orgId: string, connectionId: string, enabled: boolean) {
  return useQuery({
    queryKey: changeKeys.access(orgId, connectionId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/connections/{connection_id}/write-access`, {
          params: { path: { organization_id: orgId, connection_id: connectionId } },
        }),
      ),
  });
}

export function useSetWriteAccess(orgId: string, connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (allowed: boolean) =>
      unwrap(
        api.PUT(`${ORG}/connections/{connection_id}/write-access`, {
          params: { path: { organization_id: orgId, connection_id: connectionId } },
          body: { allowed },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(changeKeys.access(orgId, connectionId), data),
  });
}
