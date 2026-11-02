"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Agency = components["schemas"]["AgencyOut"];
export type Grant = components["schemas"]["GrantOut"];
export type Client = components["schemas"]["ClientOut"];
export type GrantIn = components["schemas"]["GrantIn"];

export const agencyKeys = {
  agency: (org: string) => ["organization", org, "agency"] as const,
  clients: (org: string) => ["organization", org, "clients"] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const path = (orgId: string) => ({ params: { path: { organization_id: orgId } } });
const grantPath = (orgId: string, grantId: string) => ({
  params: { path: { organization_id: orgId, grant_id: grantId } },
});

export function useAgency(orgId: string) {
  return useQuery({
    queryKey: agencyKeys.agency(orgId),
    queryFn: () => unwrap(api.GET(`${ORG}/agency`, path(orgId))),
  });
}

export function useClients(orgId: string) {
  return useQuery({
    queryKey: agencyKeys.clients(orgId),
    queryFn: () => unwrap(api.GET(`${ORG}/clients`, path(orgId))),
  });
}

function useChange<T>(orgId: string, call: (vars: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: call,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: agencyKeys.agency(orgId) }),
  });
}

export function useNewCode(orgId: string) {
  return useChange(orgId, () => unwrap(api.POST(`${ORG}/agency/code`, path(orgId))));
}

export function useGrant(orgId: string) {
  return useChange(orgId, (body: GrantIn) =>
    unwrap(api.POST(`${ORG}/agency/grants`, { ...path(orgId), body })),
  );
}

export function useAccept(orgId: string) {
  return useChange(orgId, (grantId: string) =>
    unwrap(api.POST(`${ORG}/agency/grants/{grant_id}/accept`, grantPath(orgId, grantId))),
  );
}

export function useRevoke(orgId: string) {
  return useChange(orgId, (grantId: string) =>
    unwrap(api.POST(`${ORG}/agency/grants/{grant_id}/revoke`, grantPath(orgId, grantId))),
  );
}
