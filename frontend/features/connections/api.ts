"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Connection = components["schemas"]["ConnectionOut"];
export type Resource = components["schemas"]["ResourceOut"];
export type Link = components["schemas"]["LinkOut"];
export type Job = components["schemas"]["JobOut"];
export type Provider = components["schemas"]["ProviderOut"];

/** Cache keys — all under the organization, so leaving it clears them together. */
export const keys = {
  providers: ["providers"] as const,
  connections: (org: string) => ["organization", org, "connections"] as const,
  connection: (org: string, id: string) => ["organization", org, "connections", id] as const,
  resources: (org: string, id: string) =>
    ["organization", org, "connections", id, "resources"] as const,
  links: (org: string, resource: string) => ["organization", org, "links", resource] as const,
  job: (org: string, job: string) => ["organization", org, "jobs", job] as const,
};

const org = (id: string) => ({ organization_id: id });

export function useProviders() {
  return useQuery({
    queryKey: keys.providers,
    queryFn: () => unwrap(api.GET("/api/v1/providers")),
    staleTime: 5 * 60_000,
  });
}

export function useConnections(orgId: string) {
  return useQuery({
    queryKey: keys.connections(orgId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/connections", {
          params: { path: org(orgId) },
        }),
      ),
  });
}

export function useConnection(orgId: string, connectionId: string) {
  return useQuery({
    queryKey: keys.connection(orgId, connectionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/connections/{connection_id}", {
          params: { path: { ...org(orgId), connection_id: connectionId } },
        }),
      ),
  });
}

const DISCOVERY_POLLS = 20;

/**
 * Accounts found through a connection. Right after connecting, discovery runs in the
 * background, so an empty list is re-checked every few seconds for a short while.
 */
export function useResources(orgId: string, connectionId: string, connectionActive: boolean) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: keys.resources(orgId, connectionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/connections/{connection_id}/resources", {
          params: { path: { ...org(orgId), connection_id: connectionId } },
        }),
      ),
    refetchInterval: (query) =>
      connectionActive &&
      query.state.status !== "error" &&
      query.state.data?.length === 0 &&
      query.state.dataUpdateCount < DISCOVERY_POLLS
        ? 3000
        : false,
  });
  // After about a minute of re-checking, stop saying "looking": discovery may have failed or the
  // platform may really have no accounts. The page then offers "Check for new accounts".
  const updates =
    queryClient.getQueryState(keys.resources(orgId, connectionId))?.dataUpdateCount ?? 0;
  const stillLooking =
    connectionActive && !query.isError && query.data?.length === 0 && updates < DISCOVERY_POLLS;
  return { ...query, stillLooking };
}

export function useLinkHistory(orgId: string, resourceId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.links(orgId, resourceId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/resources/{resource_id}/links", {
          params: { path: { ...org(orgId), resource_id: resourceId } },
        }),
      ),
    enabled,
  });
}

const FINISHED = new Set(["succeeded", "failed", "dead"]);
export const jobFinished = (job: Job | undefined) => Boolean(job && FINISHED.has(job.status));

/**
 * Follows a background job until it finishes. Stops (and reports the error) if the job can no
 * longer be read — for example after the person's role changed — instead of polling forever.
 */
export function useJob(orgId: string, jobId: string | null) {
  return useQuery({
    queryKey: keys.job(orgId, jobId ?? "none"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/organizations/{organization_id}/jobs/{job_id}", {
          params: { path: { ...org(orgId), job_id: jobId as string } },
        }),
      ),
    enabled: jobId !== null,
    refetchInterval: (query) =>
      query.state.status === "error" || jobFinished(query.state.data) ? false : 2000,
  });
}

export type StartConnection = {
  readonly provider: string;
  /** Platform-specific details, e.g. a Shopify store address ({ shop_domain }). */
  readonly params?: Record<string, string>;
};

export function useStartConnection(orgId: string) {
  return useMutation({
    mutationFn: ({ provider, params }: StartConnection) =>
      unwrap(
        api.POST("/api/v1/organizations/{organization_id}/connections/{provider}/start", {
          params: { path: { ...org(orgId), provider } },
          ...(params ? { body: { params } } : {}),
        }),
      ),
  });
}

function useConnectionMutation<T, R>(
  orgId: string,
  connectionId: string,
  fn: (vars: T) => Promise<R>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.connections(orgId) }),
        queryClient.invalidateQueries({ queryKey: keys.connection(orgId, connectionId) }),
      ]),
  });
}

export function useDisconnect(orgId: string, connectionId: string) {
  return useConnectionMutation(orgId, connectionId, () =>
    unwrap(
      api.POST("/api/v1/organizations/{organization_id}/connections/{connection_id}/disconnect", {
        params: { path: { ...org(orgId), connection_id: connectionId } },
      }),
    ),
  );
}

export function useRediscover(orgId: string, connectionId: string) {
  return useConnectionMutation(orgId, connectionId, () =>
    unwrap(
      api.POST("/api/v1/organizations/{organization_id}/connections/{connection_id}/rediscover", {
        params: { path: { ...org(orgId), connection_id: connectionId } },
      }),
    ),
  );
}

export function useLinkResource(orgId: string, connectionId: string) {
  return useConnectionMutation(
    orgId,
    connectionId,
    ({ resourceId, link }: { resourceId: string; link: boolean }) =>
      link
        ? unwrap(
            api.POST("/api/v1/organizations/{organization_id}/resources/{resource_id}/link", {
              params: { path: { ...org(orgId), resource_id: resourceId } },
            }),
          )
        : unwrap(
            api.POST("/api/v1/organizations/{organization_id}/resources/{resource_id}/unlink", {
              params: { path: { ...org(orgId), resource_id: resourceId } },
            }),
          ),
  );
}

export function useRequestSync(orgId: string) {
  return useMutation({
    mutationFn: (resourceId: string) =>
      unwrap(
        api.POST("/api/v1/organizations/{organization_id}/resources/{resource_id}/sync", {
          params: { path: { ...org(orgId), resource_id: resourceId } },
        }),
      ),
  });
}
