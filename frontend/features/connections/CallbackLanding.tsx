"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageCard } from "@/components/ui/PageCard";

import { connectError } from "./labels";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ALLOWED = ["status", "code", "connection_id"] as const;

/**
 * Where the platform sends people back (`/connections?status=…`). When the API names the
 * organization (only after it verified the person manages it), continue there; otherwise explain.
 */
export function CallbackLanding() {
  const params = useSearchParams();
  const router = useRouter();
  const orgId = params.get("organization_id");
  const target = orgId && UUID.test(orgId) ? orgId : null;

  useEffect(() => {
    if (!target) return;
    const forward = new URLSearchParams();
    for (const key of ALLOWED) {
      const value = params.get(key);
      if (value && /^[\w-]{1,64}$/.test(value)) forward.set(key, value);
    }
    router.replace(`/orgs/${target}/connections?${forward.toString()}`);
  }, [target, params, router]);

  if (target) return <PageCard title="Connecting">{<p role="status">Finishing up…</p>}</PageCard>;
  const status = params.get("status");
  return (
    <PageCard title="Connection not completed">
      <Alert tone={status === "cancelled" ? "info" : "error"}>
        {status === "cancelled"
          ? "Connection cancelled. Nothing was connected."
          : connectError(params.get("code"))}
      </Alert>
      <p>
        <Link href="/">Go to your organizations</Link>
      </p>
    </PageCard>
  );
}
