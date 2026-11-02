"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import styles from "@/features/advertising/advertising.module.css";
import { providerName } from "@/features/advertising/labels";
import {
  OrganizationNotFound,
  useCurrentOrganization,
} from "@/features/organizations/OrganizationShell";
import type { Organization } from "@/features/organizations/api";
import { formatDateTime } from "@/features/organizations/options";
import { canManageCreatives } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useArchiveAsset,
  useAssetImage,
  useAssets,
  useCreativeSet,
  useCreativeSets,
  useUploadAsset,
  type Asset,
} from "./api";
import { CreativeCard } from "./CreativeCard";
import { ASSET_REASONS } from "./labels";
import own from "./creatives.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function AssetTile({ org, asset, manage }: { org: Organization; asset: Asset; manage: boolean }) {
  const image = useAssetImage(org.id, asset.id);
  const archive = useArchiveAsset(org.id);
  const name = asset.original_name ?? "Image";
  return (
    <li className={own.card}>
      {/* eslint-disable-next-line @next/next/no-img-element -- a private blob: image */}
      {image ? <img className={own.thumb} src={image} alt={name} /> : <p role="status">Loading…</p>}
      <p>
        {name} · {asset.width} × {asset.height}
      </p>
      {manage ? (
        <Button variant="link" busy={archive.isPending} onClick={() => archive.mutate(asset.id)}>
          Archive {name}
        </Button>
      ) : null}
    </li>
  );
}

/** The organization's images: upload (checked and cleaned by AdVegaX) and archive. */
function ImageLibrary({ org }: { org: Organization }) {
  const assets = useAssets(org.id);
  const upload = useUploadAsset(org.id);
  const input = useRef<HTMLInputElement>(null);
  const manage = canManageCreatives(org.role);
  const error = upload.error;
  const reasons =
    error instanceof ApiError
      ? error.details.map((d) => ASSET_REASONS[d.reason ?? ""] ?? d.reason)
      : [];
  return (
    <section aria-labelledby="image-library" className={styles.section}>
      <h2 id="image-library">Images</h2>
      <p className={styles.muted}>
        Your own pictures for Meta ads: JPEG, PNG or WebP, at least 600 × 600 pixels, up to 10 MB.
        AdVegaX re-saves every picture, which removes hidden data such as the location it was taken.
        Images are private to your organization.
      </p>
      {manage ? (
        <div className={own.actions}>
          <label htmlFor="image-upload">Add an image</label>
          <input
            id="image-upload"
            ref={input}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                upload.mutate(file, {
                  onSettled: () => input.current && (input.current.value = ""),
                });
            }}
          />
          {upload.isPending ? <p role="status">Checking and saving the image…</p> : null}
        </div>
      ) : null}
      {error ? (
        <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
          <p>{messageFor(error)}</p>
          {reasons.length ? <p>{reasons.join(" ")}</p> : null}
        </Alert>
      ) : null}
      {assets.error ? (
        <Alert tone="error">{messageFor(assets.error)}</Alert>
      ) : !assets.data ? (
        <p role="status">Loading…</p>
      ) : assets.data.length === 0 ? (
        <p className={styles.muted}>No images yet.</p>
      ) : (
        <ul className={own.library} aria-label="Images">
          {assets.data.map((a) => (
            <AssetTile key={a.id} org={org} asset={a} manage={manage} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** Creatives: the drafts made from ready strategies, and the image library. */
export function CreativesPage() {
  const org = useCurrentOrganization();
  const sets = useCreativeSets(org.id);
  return (
    <section aria-labelledby="creatives-title">
      <PageHeading id="creatives-title">Creatives</PageHeading>
      <p className={styles.muted}>
        Ad copy drafted from your ready strategies. A person approves every creative before the
        campaign builder can use it; nothing is sent to Google or Meta here. To make new ones, open
        a strategy marked ready and choose “Make creatives”.
      </p>
      <section aria-labelledby="creative-sets" className={styles.section}>
        <h2 id="creative-sets">Drafted sets</h2>
        {sets.error ? (
          <Alert tone="error">{messageFor(sets.error)}</Alert>
        ) : !sets.data ? (
          <p role="status">Loading…</p>
        ) : sets.data.length === 0 ? (
          <p className={styles.muted}>No creatives yet.</p>
        ) : (
          <ul className={styles.list}>
            {sets.data.map((s) => (
              <li key={s.id} className={styles.card}>
                <Link href={`/orgs/${org.id}/creatives/${s.id}`}>
                  {s.product_title ?? "Product no longer in the store"}
                </Link>
                <span>
                  {s.approved} of {s.concepts} approved · {formatDateTime(s.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <ImageLibrary org={org} />
    </section>
  );
}

function LoadedSet({ org, setId }: { org: Organization; setId: string }) {
  const query = useCreativeSet(org.id, setId);
  if (query.error) {
    if (query.error instanceof ApiError && query.error.status === 404)
      return <OrganizationNotFound />;
    return <Alert tone="error">{messageFor(query.error)}</Alert>;
  }
  if (!query.data) return <p role="status">Loading…</p>;
  const data = query.data;
  const platforms = [...new Set(data.creatives.map((c) => c.platform))];
  return (
    <section aria-labelledby="set-title">
      <p>
        <Link href={`/orgs/${org.id}/creatives`}>All creatives</Link> ·{" "}
        <Link href={`/orgs/${org.id}/strategies/${data.strategy_id}`}>The strategy</Link>
      </p>
      <PageHeading id="set-title">
        Creatives for {data.product_title ?? "a product no longer in the store"}
      </PageHeading>
      <p className={styles.muted}>
        Drafted on {formatDateTime(data.created_at)}. Each creative must pass AdVegaX&apos;s checks
        and be approved by an owner, admin or manager before the campaign builder can use it.
      </p>
      {platforms.map((platform) => (
        <section key={platform} aria-labelledby={`platform-${platform}`} className={styles.section}>
          <h2 id={`platform-${platform}`}>{providerName(platform)}</h2>
          <ul className={own.cards}>
            {data.creatives
              .filter((c) => c.platform === platform)
              .map((c) => (
                <CreativeCard key={c.concept_id} org={org} setId={setId} creative={c} />
              ))}
          </ul>
        </section>
      ))}
    </section>
  );
}

/** One drafted set: every concept's newest version with its preview, checks and decisions. */
export function CreativeSetPage() {
  const org = useCurrentOrganization();
  const params = useParams<{ setId: string }>();
  const id = params.setId ?? "";
  if (!UUID.test(id)) return <OrganizationNotFound />;
  return <LoadedSet org={org} setId={id} />;
}
