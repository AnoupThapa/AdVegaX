"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { TextField } from "@/components/ui/TextField";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canManageConnections } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { goToExternal } from "@/lib/navigation/external";

import { useConnections, useProviders, useStartConnection, type Provider } from "./api";
import { CONNECT_FIELDS, normalizeShopDomain } from "./connect-fields";
import styles from "./connections.module.css";
import { connectError, connectionStatus } from "./labels";

type Notice = { tone: "success" | "error" | "info"; text: string; requestId: string | null };

/** The result the platform sent back (via /connections), shown once and removed from the URL. */
function useCallbackNotice(): Notice | null {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [notice] = useState<Notice | null>(() => {
    const status = params.get("status");
    if (status === "connected")
      return {
        tone: "success",
        text: "Connected. We are now looking for the accounts it can reach.",
        requestId: null,
      };
    if (status === "cancelled")
      return {
        tone: "info",
        text: "Connection cancelled. Nothing was connected.",
        requestId: null,
      };
    if (status === "error")
      return { tone: "error", text: connectError(params.get("code")), requestId: null };
    return null;
  });
  useEffect(() => {
    if (params.get("status")) router.replace(pathname);
  }, [params, pathname, router]);
  return notice;
}

function ConnectSection({ orgId, onNotice }: { orgId: string; onNotice: (n: Notice) => void }) {
  const providers = useProviders();
  const start = useStartConnection(orgId);

  function connect(provider: Provider, params?: Record<string, string>) {
    start.mutate(params ? { provider: provider.code, params } : { provider: provider.code }, {
      onSuccess: (result) => {
        if (!goToExternal(result.authorize_url)) {
          onNotice({ tone: "error", text: connectError(null), requestId: null });
        }
      },
      onError: (error) =>
        onNotice({
          tone: "error",
          text: messageFor(error),
          requestId: error instanceof ApiError ? error.requestId : null,
        }),
    });
  }

  return (
    <section aria-labelledby="connect-title" className={`${styles.section} ${styles.panel}`}>
      <h2 id="connect-title">Connect a platform</h2>
      {providers.error ? <Alert tone="error">{messageFor(providers.error)}</Alert> : null}
      {providers.isPending ? <p role="status">Loading platforms…</p> : null}
      {providers.data?.length === 0 ? (
        <p className={styles.muted}>
          No platforms are available to connect yet. Shopify, WooCommerce, Google Ads, Meta and
          Google Analytics will appear here as they are added.
        </p>
      ) : null}
      {providers.data?.length ? (
        <ul className={styles.list}>
          {providers.data.map((p) => (
            <li key={p.code} className={styles.card}>
              <div>
                <p className={styles.cardTitle}>{p.display_name}</p>
                {p.test_only ? (
                  <p className={styles.muted}>For testing only — not a real platform.</p>
                ) : null}
              </div>
              {CONNECT_FIELDS[p.code] ? (
                <ConnectForm
                  provider={p}
                  busy={start.isPending && start.variables?.provider === p.code}
                  disabled={start.isPending}
                  onConnect={(params) => connect(p, params)}
                />
              ) : (
                <Button
                  busy={start.isPending && start.variables?.provider === p.code}
                  disabled={start.isPending}
                  aria-label={`Connect ${p.display_name}`}
                  onClick={() => connect(p)}
                >
                  Connect
                </Button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <p className={styles.muted}>
        You will sign in on the platform&apos;s own page and choose what AdVegaX may read. We never
        see your password there.
      </p>
    </section>
  );
}

/** A platform that needs details first (e.g. the Shopify store address). */
function ConnectForm({
  provider,
  busy,
  disabled,
  onConnect,
}: {
  provider: Provider;
  busy: boolean;
  disabled: boolean;
  onConnect: (params: Record<string, string>) => void;
}) {
  const fields = CONNECT_FIELDS[provider.code] ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  function submit(event: FormEvent) {
    event.preventDefault();
    const shop = normalizeShopDomain(values.shop_domain ?? "");
    if (fields.some((f) => f.name === "shop_domain") && !shop) {
      setErrors({ shop_domain: "Enter a store address like your-store.myshopify.com." });
      return;
    }
    setErrors({});
    onConnect(shop ? { shop_domain: shop } : {});
  }

  return (
    <form
      className={styles.connectForm}
      onSubmit={submit}
      aria-label={`Connect ${provider.display_name}`}
      noValidate
    >
      {fields.map((field) => (
        <TextField
          key={field.name}
          label={field.label}
          hint={field.hint}
          placeholder={field.placeholder}
          required
          autoComplete="off"
          spellCheck={false}
          maxLength={255}
          value={values[field.name] ?? ""}
          errors={errors[field.name] ? [errors[field.name] as string] : []}
          onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
        />
      ))}
      <Button type="submit" busy={busy} disabled={disabled}>
        Connect {provider.display_name}
      </Button>
    </form>
  );
}

export function ConnectionsPage() {
  const org = useCurrentOrganization();
  const connections = useConnections(org.id);
  const providers = useProviders();
  const callbackNotice = useCallbackNotice();
  const [notice, setNotice] = useState<Notice | null>(null);
  const shown = notice ?? callbackNotice;
  const manage = canManageConnections(org.role);
  const providerName = (code: string) =>
    providers.data?.find((p) => p.code === code)?.display_name ?? code;

  return (
    <section aria-labelledby="connections-title">
      <PageHeading id="connections-title">Connections</PageHeading>
      {shown ? (
        <Alert tone={shown.tone} requestId={shown.requestId}>
          {shown.text}
        </Alert>
      ) : null}

      <section aria-labelledby="your-connections" className={styles.section}>
        <h2 id="your-connections">Your connections</h2>
        {connections.error ? <Alert tone="error">{messageFor(connections.error)}</Alert> : null}
        {connections.isPending ? <p role="status">Loading connections…</p> : null}
        {connections.data?.length === 0 ? <p>Nothing is connected yet.</p> : null}
        {connections.data?.length ? (
          <ul className={styles.list}>
            {connections.data.map((c) => {
              const status = connectionStatus(c.status);
              return (
                <li key={c.id} className={styles.card}>
                  <div>
                    <p className={styles.cardTitle}>
                      <Link href={`/orgs/${org.id}/connections/${c.id}`}>
                        {providerName(c.provider)}
                        {c.account_label ? ` — ${c.account_label}` : ""}
                      </Link>
                    </p>
                    <p className={styles.muted}>
                      Connected{" "}
                      {new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
                        new Date(c.created_at),
                      )}
                      {c.last_error_code && c.status !== "active"
                        ? ` · ${connectError(c.last_error_code)}`
                        : ""}
                    </p>
                  </div>
                  <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span>
                </li>
              );
            })}
          </ul>
        ) : null}
      </section>

      {manage ? (
        <ConnectSection orgId={org.id} onNotice={setNotice} />
      ) : (
        <p className={styles.muted}>Only owners, admins and managers can connect platforms.</p>
      )}
    </section>
  );
}
