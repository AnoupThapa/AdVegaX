"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Billing = components["schemas"]["BillingOut"];
export type Plan = components["schemas"]["PlanOut"];
export type CheckoutIn = components["schemas"]["CheckoutIn"];

export const billingKeys = {
  billing: (org: string) => ["organization", org, "billing"] as const,
  plans: () => ["billing", "plans"] as const,
};

const ORG = "/api/v1/organizations/{organization_id}" as const;
const path = (orgId: string) => ({ params: { path: { organization_id: orgId } } });

export function useBilling(orgId: string) {
  return useQuery({
    queryKey: billingKeys.billing(orgId),
    queryFn: () => unwrap(api.GET(`${ORG}/billing`, path(orgId))),
  });
}

export function usePlans() {
  return useQuery({
    queryKey: billingKeys.plans(),
    queryFn: () => unwrap(api.GET("/api/v1/billing/plans")),
    staleTime: Infinity,
  });
}

/** Stripe's own pages: AdVegaX never sees card details (Q-13-5). */
export function goTo(url: string) {
  window.location.assign(url);
}

export function useCheckout(orgId: string) {
  return useMutation({
    mutationFn: (body: CheckoutIn) =>
      unwrap(api.POST(`${ORG}/billing/checkout`, { ...path(orgId), body })),
    onSuccess: (data) => goTo(data.url),
  });
}

export function usePortal(orgId: string) {
  return useMutation({
    mutationFn: () => unwrap(api.POST(`${ORG}/billing/portal`, path(orgId))),
    onSuccess: (data) => goTo(data.url),
  });
}
