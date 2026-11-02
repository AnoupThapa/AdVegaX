"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SESSION_KEY } from "@/features/auth/session";
import { api, unwrap } from "@/lib/api";
import type { components } from "@/lib/api/schema";

export type Organization = components["schemas"]["OrganizationOut"];
export type Member = components["schemas"]["MemberOut"];
export type Invitation = components["schemas"]["InvitationOut"];
export type OrganizationCreate = components["schemas"]["OrganizationCreate"];
export type OrganizationUpdate = components["schemas"]["OrganizationUpdate"];
type AssignableRole = components["schemas"]["InvitationCreate"]["role"];

/** Cache keys. Everything for one organization sits under ["organization", id]. */
export const organizationKey = (id: string) => ["organization", id] as const;
export const membersKey = (id: string) => ["organization", id, "members"] as const;
export const invitationsKey = (id: string) => ["organization", id, "invitations"] as const;

const orgPath = (id: string) => ({ params: { path: { organization_id: id } } });

export function useOrganization(id: string) {
  return useQuery({
    queryKey: organizationKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/organizations/{organization_id}", orgPath(id))),
  });
}

export function useMembers(id: string) {
  return useQuery({
    queryKey: membersKey(id),
    queryFn: () => unwrap(api.GET("/api/v1/organizations/{organization_id}/members", orgPath(id))),
  });
}

export function useInvitations(id: string, enabled: boolean) {
  return useQuery({
    queryKey: invitationsKey(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/organizations/{organization_id}/invitations", orgPath(id))),
    enabled,
  });
}

export function useCreateOrganization() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OrganizationCreate) => unwrap(api.POST("/api/v1/organizations", { body })),
    onSuccess: async (org) => {
      queryClient.setQueryData(organizationKey(org.id), org);
      // The session lists memberships (used by the organization switcher).
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
}

export function useUpdateOrganization(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OrganizationUpdate) =>
      unwrap(api.PATCH("/api/v1/organizations/{organization_id}", { ...orgPath(id), body })),
    onSuccess: async (org) => {
      queryClient.setQueryData(organizationKey(id), org);
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
}

export function useChangeMemberRole(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: AssignableRole }) =>
      unwrap(
        api.PATCH("/api/v1/organizations/{organization_id}/members/{member_id}", {
          params: { path: { organization_id: id, member_id: memberId } },
          body: { role },
        }),
      ),
    // Refresh the organization too: the caller may have changed their own role.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: membersKey(id) }),
        queryClient.invalidateQueries({ queryKey: organizationKey(id), exact: true }),
        queryClient.invalidateQueries({ queryKey: SESSION_KEY }),
      ]),
  });
}

export function useRemoveMember(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) =>
      unwrap(
        api.DELETE("/api/v1/organizations/{organization_id}/members/{member_id}", {
          params: { path: { organization_id: id, member_id: memberId } },
        }),
      ),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: membersKey(id) }),
        queryClient.invalidateQueries({ queryKey: SESSION_KEY }),
      ]),
  });
}

export function useCreateInvitation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: AssignableRole }) =>
      unwrap(
        api.POST("/api/v1/organizations/{organization_id}/invitations", { ...orgPath(id), body }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: invitationsKey(id) }),
  });
}

export function useRevokeInvitation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      unwrap(
        api.DELETE("/api/v1/organizations/{organization_id}/invitations/{invitation_id}", {
          params: { path: { organization_id: id, invitation_id: invitationId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: invitationsKey(id) }),
  });
}

export function useAcceptInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      unwrap(api.POST("/api/v1/invitations/accept", { body: { token } })),
    onSuccess: async (org) => {
      queryClient.setQueryData(organizationKey(org.id), org);
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    },
  });
}
