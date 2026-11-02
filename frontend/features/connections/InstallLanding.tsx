"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageCard } from "@/components/ui/PageCard";
import { SelectField } from "@/components/ui/SelectField";
import { useSession } from "@/features/auth/session";
import { canManageConnections, roleLabel } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { goToExternal } from "@/lib/navigation/external";

import { useProviders, useStartConnection } from "./api";
import { normalizeShopDomain } from "./connect-fields";
import { connectError } from "./labels";

const PROVIDER = /^[a-z0-9_]{1,32}$/;

/**
 * Where a platform-initiated install lands (`/connect/shopify?account=…`, task 2A-10). The API
 * verified the platform's signature and stored nothing; here the signed-in person chooses
 * which organization gets the store, then approves the connection on the platform as usual.
 */
export function InstallLanding() {
  const params = useParams<{ provider: string }>();
  const search = useSearchParams();
  const provider = params.provider ?? "";
  const account = normalizeShopDomain(search.get("account") ?? "");
  if (!PROVIDER.test(provider) || provider !== "shopify" || !account) {
    return (
      <PageCard title="Install link not valid">
        <Alert tone="error">
          This install link is incomplete or not valid. Start again from your Shopify admin.
        </Alert>
        <p>
          <Link href="/">Go to your organizations</Link>
        </p>
      </PageCard>
    );
  }
  return <ChooseOrganization provider={provider} account={account} />;
}

function ChooseOrganization({ provider, account }: { provider: string; account: string }) {
  const { user } = useSession();
  const providers = useProviders();
  const eligible = (user?.memberships ?? []).filter((m) => canManageConnections(m.role));
  const [orgId, setOrgId] = useState<string>(eligible[0]?.organization_id ?? "");
  const start = useStartConnection(orgId);
  const [error, setError] = useState<{ text: string; requestId: string | null } | null>(null);
  const name = providers.data?.find((p) => p.code === provider)?.display_name ?? "Shopify";

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!orgId) return;
    setError(null);
    start.mutate(
      { provider, params: { shop_domain: account } },
      {
        onSuccess: (result) => {
          if (!goToExternal(result.authorize_url))
            setError({ text: connectError(null), requestId: null });
        },
        onError: (e) =>
          setError({ text: messageFor(e), requestId: e instanceof ApiError ? e.requestId : null }),
      },
    );
  }

  return (
    <PageCard title={`Connect ${name}`}>
      <p>
        Choose the AdVegaX organization for the store <strong>{account}</strong>. You will then
        approve read-only access on {name}.
      </p>
      {error ? (
        <Alert tone="error" requestId={error.requestId}>
          {error.text}
        </Alert>
      ) : null}
      {eligible.length === 0 ? (
        <>
          <Alert tone="info">
            You need to be an owner, admin or manager of an organization to connect a store.
          </Alert>
          <p>
            <Link href="/orgs/new">Create an organization</Link>, then open the install link again.
          </p>
        </>
      ) : (
        <form onSubmit={submit}>
          <SelectField
            label="Organization"
            options={eligible.map((m) => ({
              value: m.organization_id,
              label: `${m.organization_name} (${roleLabel(m.role)})`,
            }))}
            value={orgId}
            onChange={(event) => setOrgId(event.target.value)}
          />
          <Button type="submit" busy={start.isPending}>
            Continue to {name}
          </Button>
        </form>
      )}
    </PageCard>
  );
}
