"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { api, unwrap } from "@/lib/api";
import { apiErrorFrom } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type CreativeSet = components["schemas"]["CreativeSetOut"];
export type CreativeSetSummary = components["schemas"]["CreativeSetSummaryOut"];
export type Creative = components["schemas"]["CreativeOut"];
export type Check = components["schemas"]["CheckOut"];
export type Asset = components["schemas"]["AssetOut"];
export type CreativeRules = components["schemas"]["CreativeRulesOut"];

export type GoogleContent = {
  headlines: string[];
  descriptions: string[];
  path1: string;
  path2: string;
};
export type MetaContent = {
  primary_texts: string[];
  headlines: string[];
  descriptions: string[];
  call_to_action: string;
};

export const creativeKeys = {
  all: (org: string) => ["organization", org, "creatives"] as const,
  sets: (org: string, strategy: string) =>
    ["organization", org, "creatives", "sets", strategy] as const,
  set: (org: string, id: string) => ["organization", org, "creatives", "set", id] as const,
  assets: (org: string) => ["organization", org, "creatives", "assets"] as const,
  rules: (org: string) => ["organization", org, "creative-rules"] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const ONE = `${ORG}/creatives/{creative_id}` as const;

export function useCreativeSets(orgId: string, strategyId = "") {
  return useQuery({
    queryKey: creativeKeys.sets(orgId, strategyId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/creative-sets`, {
          params: {
            path: { organization_id: orgId },
            query: strategyId ? { strategy_id: strategyId } : {},
          },
        }),
      ),
  });
}

export function useCreativeSet(orgId: string, setId: string) {
  return useQuery({
    queryKey: creativeKeys.set(orgId, setId),
    queryFn: () =>
      unwrap(
        api.GET(`${ORG}/creative-sets/{set_id}`, {
          params: { path: { organization_id: orgId, set_id: setId } },
        }),
      ),
  });
}

export function useGenerateCreatives(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(
        api.POST(`${ORG}/ai/creative-sets`, {
          params: { path: { organization_id: orgId } },
          body: { strategy_id: strategyId },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: creativeKeys.all(orgId) }),
  });
}

/** Every change to a creative answers with the creative as saved; the set is read again. */
function useCreativeChange<T>(orgId: string, setId: string, call: (body: T) => Promise<Creative>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSettled: () => queryClient.invalidateQueries({ queryKey: creativeKeys.set(orgId, setId) }),
  });
}

export function useUpdateCreative(orgId: string, setId: string) {
  return useCreativeChange(
    orgId,
    setId,
    (body: {
      id: string;
      content?: Record<string, unknown>;
      asset_id?: string | null;
      remove_asset?: boolean;
    }) =>
      unwrap(
        api.PATCH(ONE, {
          params: { path: { organization_id: orgId, creative_id: body.id } },
          body: {
            content: body.content ?? null,
            asset_id: body.asset_id ?? null,
            remove_asset: body.remove_asset ?? false,
          },
        }),
      ),
  );
}

export function useApprove(orgId: string, setId: string) {
  return useCreativeChange(orgId, setId, (body: { id: string; confirm: boolean }) =>
    unwrap(
      api.POST(`${ONE}/approve`, {
        params: { path: { organization_id: orgId, creative_id: body.id } },
        body: { confirm_flags: body.confirm },
      }),
    ),
  );
}

export function useReject(orgId: string, setId: string) {
  return useCreativeChange(orgId, setId, (body: { id: string; reason: string }) =>
    unwrap(
      api.POST(`${ONE}/reject`, {
        params: { path: { organization_id: orgId, creative_id: body.id } },
        body: { reason: body.reason },
      }),
    ),
  );
}

export function useArchiveCreative(orgId: string, setId: string) {
  return useCreativeChange(orgId, setId, (id: string) =>
    unwrap(
      api.POST(`${ONE}/archive`, {
        params: { path: { organization_id: orgId, creative_id: id } },
      }),
    ),
  );
}

export function useAssets(orgId: string) {
  return useQuery({
    queryKey: creativeKeys.assets(orgId),
    queryFn: () =>
      unwrap(api.GET(`${ORG}/creative-assets`, { params: { path: { organization_id: orgId } } })),
  });
}

export function useUploadAsset(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        api.POST(`${ORG}/creative-assets`, {
          params: { path: { organization_id: orgId } },
          // The browser sets the multipart boundary itself.
          body: form as unknown as { file: string },
        }),
      );
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: creativeKeys.assets(orgId) }),
  });
}

export function useArchiveAsset(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST(`${ORG}/creative-assets/{asset_id}/archive`, {
          params: { path: { organization_id: orgId, asset_id: id } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: creativeKeys.assets(orgId) }),
  });
}

/**
 * An image read through the API (session cookie) and shown from a local `blob:` address, so no
 * image is ever on a public link and the page's security policy needs no other image source.
 */
export function useAssetImage(orgId: string, assetId: string | null | undefined): string | null {
  const query = useQuery({
    queryKey: [...creativeKeys.assets(orgId), "content", assetId ?? ""],
    enabled: Boolean(assetId),
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const result = await api.GET(`${ORG}/creative-assets/{asset_id}/content`, {
        params: { path: { organization_id: orgId, asset_id: assetId ?? "" } },
        parseAs: "blob",
      });
      if (!result.response.ok || !(result.data instanceof Blob)) {
        throw apiErrorFrom(result.response.status, result.error, result.response.headers);
      }
      return result.data;
    },
  });
  const url = useMemo(
    () =>
      query.data && typeof URL.createObjectURL === "function"
        ? URL.createObjectURL(query.data)
        : null,
    [query.data],
  );
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

export function useCreativeRules(orgId: string) {
  return useQuery({
    queryKey: creativeKeys.rules(orgId),
    queryFn: () =>
      unwrap(api.GET(`${ORG}/creative-rules`, { params: { path: { organization_id: orgId } } })),
  });
}

export function useSaveCreativeRules(orgId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { prohibited_terms: string[]; allowed_caps: string[] }) =>
      unwrap(
        api.PUT(`${ORG}/creative-rules`, { params: { path: { organization_id: orgId } }, body }),
      ),
    onSuccess: (data) => queryClient.setQueryData(creativeKeys.rules(orgId), data),
  });
}
