"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import styles from "@/features/advertising/advertising.module.css";
import { useAdAccounts } from "@/features/advertising/api";
import { reasonText } from "@/features/changes/labels";
import own from "@/features/changes/changes.module.css";
import type { Organization } from "@/features/organizations/api";
import { canRequestChanges } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useCreateDraft, useDrafts } from "./api";

const PLATFORMS = [
  { value: "google_ads", label: "Google Ads (Search)" },
  { value: "meta_ads", label: "Meta (Sales)" },
] as const;
const STATUS: Record<string, string> = {
  draft: "being prepared",
  launching: "being created",
  created: "created, paused",
  live: "live",
  failed: "not fully created, paused",
  archived: "archived",
};

/** On a ready strategy: its campaigns, and "Build campaign" (Phase 10B). */
export function StrategyCampaigns({
  org,
  strategyId,
  ready,
  platforms,
}: {
  org: Organization;
  strategyId: string;
  ready: boolean;
  platforms: readonly string[];
}) {
  const router = useRouter();
  const drafts = useDrafts(org.id, strategyId);
  const accounts = useAdAccounts(org.id);
  const create = useCreateDraft(org.id);
  const [platform, setPlatform] = useState<string>(platforms[0] ?? "google_ads");
  const [account, setAccount] = useState("");
  const choices = (accounts.data ?? []).filter(
    (a) => a.provider === platform && a.linked && a.status === "active",
  );
  const error = create.error;
  return (
    <section aria-labelledby="strategy-campaigns" className={styles.section}>
      <h2 id="strategy-campaigns">Campaigns</h2>
      {drafts.data?.length ? (
        <ul>
          {drafts.data.map((d) => (
            <li key={d.id}>
              <Link href={`/orgs/${org.id}/builder/${d.id}`}>{d.name}</Link> —{" "}
              {STATUS[d.status] ?? d.status}
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>No campaigns yet.</p>
      )}
      {!ready ? (
        <p className={styles.muted}>Mark the strategy ready and approve its creatives first.</p>
      ) : canRequestChanges(org.role) ? (
        <div className={own.form}>
          <SelectField
            label="Platform"
            options={PLATFORMS.filter((p) => platforms.includes(p.value))}
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value);
              setAccount("");
            }}
          />
          {choices.length > 1 ? (
            <SelectField
              label="Ad account"
              placeholder="Choose an ad account"
              options={choices.map((a) => ({
                value: a.id,
                label: a.name ?? a.external_account_id,
              }))}
              value={account}
              onChange={(e) => setAccount(e.target.value)}
            />
          ) : null}
          {error ? (
            <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
              {messageFor(error)}
              {error instanceof ApiError && error.details.length
                ? ` ${error.details.map((d) => reasonText(d.reason ?? null)).join(" ")}`
                : ""}
            </Alert>
          ) : null}
          <div className={own.actions}>
            <Button
              busy={create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    strategy_id: strategyId,
                    platform: platform as "google_ads" | "meta_ads",
                    ad_account_id:
                      account || (choices.length === 1 ? choices[0]?.id : null) || null,
                  },
                  { onSuccess: (d) => router.push(`/orgs/${org.id}/builder/${d.id}`) },
                )
              }
            >
              Build campaign
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
