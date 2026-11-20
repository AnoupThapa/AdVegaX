"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useAccept, useAgency, useGrant, useNewCode, useRevoke, type Grant } from "./api";

const ROLES = [
  { value: "manager", label: "Manager — works on connections, campaigns and changes" },
  { value: "analyst", label: "Analyst — views data and plans strategies" },
  { value: "viewer", label: "Viewer — views data" },
];
const ROLE: Record<string, string> = { manager: "Manager", analyst: "Analyst", viewer: "Viewer" };
const STATUS: Record<string, string> = {
  pending: "waiting for the agency to accept",
  active: "has access",
  revoked: "ended",
};
const REASONS: Record<string, string> = {
  unknown_agency_code: "No agency has this code. Check it with your agency.",
  own_code: "This is your own organization's code.",
};

function refusal(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.details.map((d) => String(d.reason ?? "")).find((r) => r in REASONS);
    if (reason) return REASONS[reason] ?? "";
    if (error.status === 409) return "This agency already has, or has been offered, access.";
  }
  return messageFor(error);
}

/** Settings → Agency access (Phase 14): agencies working here; for an agency, its clients. */
export function AgencySettings({ org }: { org: Organization }) {
  const agency = useAgency(org.id);
  const data = agency.data;
  if (agency.error) return <Alert tone="error">{messageFor(agency.error)}</Alert>;
  if (!data || !data.enabled || org.via_agency) return null;
  return (
    <section aria-labelledby="agency-settings" className={styles.section}>
      <h2 id="agency-settings">Agency access</h2>
      <p className={styles.muted}>
        An agency can work in this organization with a role you choose — never as an owner or admin.
        It never sees your members or billing, everything its people do is in your audit log, and
        you can end it at any time.
      </p>
      <GrantList orgId={org.id} grants={data.agencies} side="client" canManage={data.can_manage} />
      {data.can_grant ? <GrantForm orgId={org.id} /> : null}
      {data.can_manage ? <AgencyCode orgId={org.id} code={data.code ?? null} /> : null}
      {data.clients.length ? (
        <>
          <h3>Organizations that gave this one access</h3>
          <GrantList
            orgId={org.id}
            grants={data.clients}
            side="agency"
            canManage={data.can_manage}
          />
          <p>
            <Link href={`/orgs/${org.id}/clients`}>See all clients</Link>
          </p>
        </>
      ) : null}
    </section>
  );
}

function GrantList({
  orgId,
  grants,
  side,
  canManage,
}: {
  orgId: string;
  grants: Grant[];
  side: "client" | "agency";
  canManage: boolean;
}) {
  const accept = useAccept(orgId);
  const revoke = useRevoke(orgId);
  if (!grants.length) {
    return side === "client" ? <p>No agency has access.</p> : null;
  }
  const error = accept.error ?? revoke.error;
  return (
    <>
      <ul className={styles.list} aria-label={side === "client" ? "Agencies" : "Clients"}>
        {grants.map((g) => {
          const other = side === "client" ? g.agency_name : g.client_name;
          return (
            <li key={g.id} className={styles.card}>
              <p>
                <strong>{other}</strong> — {ROLE[g.role] ?? g.role}, {STATUS[g.status] ?? g.status}
              </p>
              {canManage && side === "agency" && g.status === "pending" ? (
                <Button busy={accept.isPending} onClick={() => accept.mutate(g.id)}>
                  Accept {other}
                </Button>
              ) : null}{" "}
              {canManage && g.status !== "revoked" ? (
                <Button
                  variant="secondary"
                  busy={revoke.isPending}
                  onClick={() => revoke.mutate(g.id)}
                >
                  End access for {other}
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {error ? <Alert tone="error">{refusal(error)}</Alert> : null}
    </>
  );
}

function GrantForm({ orgId }: { orgId: string }) {
  const grant = useGrant(orgId);
  const [code, setCode] = useState("");
  const [role, setRole] = useState("manager");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    grant.mutate(
      { code, role: role as "manager" | "analyst" | "viewer" },
      { onSuccess: () => setCode("") },
    );
  };
  return (
    <form aria-label="Give an agency access" onSubmit={submit} className={styles.panel}>
      <TextField
        label="Agency code"
        hint="Your agency finds it in its own Settings → Agency access."
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
        minLength={6}
        maxLength={32}
      />
      <SelectField
        label="Their role here"
        options={ROLES}
        value={role}
        onChange={(e) => setRole(e.target.value)}
      />
      <Button type="submit" busy={grant.isPending}>
        Give access
      </Button>
      {grant.isSuccess ? (
        <Alert tone="success">Access offered. It starts when the agency accepts it.</Alert>
      ) : null}
      {grant.error ? <Alert tone="error">{refusal(grant.error)}</Alert> : null}
    </form>
  );
}

function AgencyCode({ orgId, code }: { orgId: string; code: string | null }) {
  const change = useNewCode(orgId);
  return (
    <div className={styles.panel}>
      <h3>Working as an agency</h3>
      <p className={styles.muted}>
        Give this code to a client. Their owner enters it in their Settings; you then accept here. A
        new code stops the old one working; access already given stays.
      </p>
      {code ? (
        <p>
          Your agency code: <strong>{code}</strong>
        </p>
      ) : null}
      <Button variant="secondary" busy={change.isPending} onClick={() => change.mutate()}>
        {code ? "Make a new code" : "Get an agency code"}
      </Button>
      {change.error ? <Alert tone="error">{messageFor(change.error)}</Alert> : null}
    </div>
  );
}
