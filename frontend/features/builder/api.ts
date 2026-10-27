"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { changeKeys } from "@/features/changes/api";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Draft = components["schemas"]["DraftOut"];
export type DraftPreview = components["schemas"]["DraftPreviewOut"];
export type DraftUpdate = components["schemas"]["DraftUpdateIn"];
export type MetaAsset = components["schemas"]["MetaAssetOut"];

export const draftKeys = {
  all: (org: string) => ["organization", org, "campaign-drafts"] as const,
  list: (org: string, strategy: string) =>
    ["organization", org, "campaign-drafts", "list", strategy] as const,
  one: (org: string, id: string) => ["organization", org, "campaign-drafts", "one", id] as const,
  assets: (org: string, account: string, kind: string) =>
    ["organization", org, "meta-assets", account, kind] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const ONE = `${ORG}/campaign-drafts/{draft_id}` as const;
const path = (orgId: string, id: string) => ({
  params: { path: { organization_id: orgId, draft_id: id } },
});
// A launch in progress is read again every few seconds until it settles.
const MOVING = new Set(["launching"]);

export function useDrafts(orgId: string, strategyId: string) {
  return useQuery({
    queryKey: draftKeys.list(orgId, strategyId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/campaign-drafts`, {
          params: { path: { organization_id: orgId }, query: { strategy_id: strategyId } },
        }),
      ),
  });
}

export function useDraft(orgId: string, draftId: string) {
  return useQuery({
    queryKey: draftKeys.one(orgId, draftId),
    queryFn: () => unwrap(api.GET(ONE, path(orgId, draftId))),
    refetchInterval: (query) =>
      MOVING.has(query.state.data?.status ?? "") || query.state.data?.open_action_id ? 3000 : false,
  });
}

export function useCreateDraft(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: components["schemas"]["DraftCreateIn"]) =>
      unwrap(
        api.POST(`${ORG}/campaign-drafts`, { params: { path: { organization_id: orgId } }, body }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: draftKeys.all(orgId) }),
  });
}

function useDraftChange<T, R>(orgId: string, draftId: string, call: (vars: T) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: draftKeys.all(orgId) }),
        queryClient.invalidateQueries({ queryKey: changeKeys.all(orgId) }),
      ]),
  });
}

export function useUpdateDraft(orgId: string, draftId: string) {
  return useDraftChange(orgId, draftId, (body: DraftUpdate) =>
    unwrap(api.PATCH(ONE, { ...path(orgId, draftId), body })),
  );
}

export function useValidateDraft(orgId: string, draftId: string) {
  return useMutation({
    mutationFn: () => unwrap(api.POST(`${ONE}/validate`, path(orgId, draftId))),
  });
}

export function useLaunchDraft(orgId: string, draftId: string) {
  return useDraftChange(orgId, draftId, () =>
    unwrap(api.POST(`${ONE}/launch`, path(orgId, draftId))),
  );
}

export function useGoLive(orgId: string, draftId: string) {
  return useDraftChange(orgId, draftId, () =>
    unwrap(api.POST(`${ONE}/go-live`, path(orgId, draftId))),
  );
}

export function useCleanUp(orgId: string, draftId: string) {
  return useDraftChange(orgId, draftId, () =>
    unwrap(api.POST(`${ONE}/clean-up`, path(orgId, draftId))),
  );
}

export function useMetaAssets(
  orgId: string,
  accountId: string,
  kind: "meta-pages" | "meta-pixels",
  enabled: boolean,
) {
  return useQuery({
    queryKey: draftKeys.assets(orgId, accountId, kind),
    enabled,
    retry: false,
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/ad-accounts/{ad_account_id}/${kind}`, {
          params: { path: { organization_id: orgId, ad_account_id: accountId } },
        }),
      ),
  });
}
