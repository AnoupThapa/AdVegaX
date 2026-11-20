"use client";

import { useId, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import ui from "@/components/ui/ui.module.css";
import styles from "@/features/advertising/advertising.module.css";
import { providerName } from "@/features/advertising/labels";
import type { Organization } from "@/features/organizations/api";
import { formatDateTime } from "@/features/organizations/options";
import { canApproveCreatives, canManageCreatives } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useApprove,
  useArchiveCreative,
  useAssetImage,
  useAssets,
  useReject,
  useUpdateCreative,
  type Creative,
  type GoogleContent,
  type MetaContent,
} from "./api";
import { CALLS_TO_ACTION, CREATIVE_STATUS, checkText } from "./labels";
import own from "./creatives.module.css";

const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

function GooglePreview({ content }: { content: GoogleContent }) {
  const path = [content.path1, content.path2].filter(Boolean).join("/");
  return (
    <div className={own.preview} aria-label="Google Ads preview">
      <p className={own.adLabel}>Sponsored</p>
      <p className={own.adUrl}>your-store{path ? ` › ${path.replaceAll("/", " › ")}` : ""}</p>
      <p className={own.adHeadline}>{content.headlines.slice(0, 3).join(" | ")}</p>
      <p>{content.descriptions[0]}</p>
      <details>
        <summary>
          All {content.headlines.length} headlines and {content.descriptions.length} descriptions
        </summary>
        <ol>
          {content.headlines.map((h, i) => (
            <li key={`h-${i}`}>{h}</li>
          ))}
        </ol>
        <ol>
          {content.descriptions.map((d, i) => (
            <li key={`d-${i}`}>{d}</li>
          ))}
        </ol>
      </details>
      <p className={styles.muted}>Google combines these lines itself; this is one example.</p>
    </div>
  );
}

function MetaPreview({
  org,
  content,
  assetId,
}: {
  org: Organization;
  content: MetaContent;
  assetId: string | null | undefined;
}) {
  const image = useAssetImage(org.id, assetId);
  return (
    <div className={own.preview} aria-label="Meta preview">
      <p className={own.adLabel}>Sponsored</p>
      <p>{content.primary_texts[0]}</p>
      {/* eslint-disable-next-line @next/next/no-img-element -- a private blob: image */}
      {image ? <img className={own.adImage} src={image} alt="The ad's image" /> : null}
      {!assetId ? <p className={styles.muted}>No image chosen yet.</p> : null}
      <p className={own.adHeadline}>{content.headlines[0]}</p>
      {content.descriptions[0] ? <p>{content.descriptions[0]}</p> : null}
      <span className={own.cta}>
        {CALLS_TO_ACTION[content.call_to_action] ?? content.call_to_action}
      </span>
      {content.primary_texts.length + content.headlines.length > 2 ? (
        <details>
          <summary>All text options</summary>
          <ul>
            {[...content.primary_texts, ...content.headlines, ...content.descriptions].map(
              (t, i) => (
                <li key={`t-${i}`}>{t}</li>
              ),
            )}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function Lines({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint: string;
}) {
  const id = useId();
  return (
    <div className={ui.field}>
      <label htmlFor={id} className={ui.label}>
        {label}
      </label>
      <p id={`${id}-hint`} className={ui.hint}>
        {hint}
      </p>
      <textarea
        id={id}
        aria-describedby={`${id}-hint`}
        className={`${ui.input} ${own.textarea}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function ErrorList({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? error.details : [];
  return (
    <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
      <p>{messageFor(error)}</p>
      {details.length ? (
        <ul>
          {details.map((d, i) => (
            <li key={`e-${i}`}>
              {d.reason && d.field
                ? checkText({ code: d.reason, field: d.field, detail: d.detail ?? null })
                : (d.issue ?? d.reason ?? "")}
            </li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

function EditForm({
  org,
  setId,
  creative,
  onDone,
}: {
  org: Organization;
  setId: string;
  creative: Creative;
  onDone: () => void;
}) {
  const google = creative.platform === "google_ads";
  const g = creative.content as unknown as GoogleContent;
  const m = creative.content as unknown as MetaContent;
  const [headlines, setHeadlines] = useState((google ? g.headlines : m.headlines).join("\n"));
  const [descriptions, setDescriptions] = useState(
    (google ? g.descriptions : m.descriptions).join("\n"),
  );
  const [primary, setPrimary] = useState(google ? "" : m.primary_texts.join("\n"));
  const [path1, setPath1] = useState(google ? g.path1 : "");
  const [path2, setPath2] = useState(google ? g.path2 : "");
  const [cta, setCta] = useState(google ? "" : m.call_to_action);
  const [asset, setAsset] = useState(creative.asset?.id ?? "");
  const assets = useAssets(org.id);
  const update = useUpdateCreative(org.id, setId);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const content = google
      ? {
          headlines: lines(headlines),
          descriptions: lines(descriptions),
          path1: path1.trim(),
          path2: path2.trim(),
        }
      : {
          primary_texts: lines(primary),
          headlines: lines(headlines),
          descriptions: lines(descriptions),
          call_to_action: cta,
        };
    update.mutate(
      {
        id: creative.id,
        content,
        ...(google ? {} : asset ? { asset_id: asset } : { remove_asset: true }),
      },
      { onSuccess: onDone },
    );
  };

  return (
    <form className={own.form} onSubmit={submit} noValidate aria-label={`Edit ${creative.angle}`}>
      {!google ? (
        <Lines
          label="Primary texts"
          value={primary}
          onChange={setPrimary}
          hint="One per line; up to 5, at most 125 characters each."
        />
      ) : null}
      <Lines
        label="Headlines"
        value={headlines}
        onChange={setHeadlines}
        hint={
          google
            ? "One per line; 3 to 15, at most 30 characters each."
            : "One per line; up to 5, at most 40 characters each."
        }
      />
      <Lines
        label="Descriptions"
        value={descriptions}
        onChange={setDescriptions}
        hint={
          google
            ? "One per line; 2 to 4, at most 90 characters each."
            : "One per line; up to 5, at most 30 characters each."
        }
      />
      {google ? (
        <>
          <TextField
            label="Display path 1"
            value={path1}
            onChange={(e) => setPath1(e.target.value)}
          />
          <TextField
            label="Display path 2"
            value={path2}
            onChange={(e) => setPath2(e.target.value)}
          />
        </>
      ) : (
        <>
          <SelectField
            label="Call to action"
            options={Object.entries(CALLS_TO_ACTION).map(([value, label]) => ({ value, label }))}
            value={cta}
            onChange={(e) => setCta(e.target.value)}
          />
          <SelectField
            label="Image"
            options={[
              { value: "", label: "No image" },
              ...(assets.data ?? []).map((a) => ({
                value: a.id,
                label: `${a.original_name ?? "Image"} (${a.width} × ${a.height})`,
              })),
              ...(creative.asset && !(assets.data ?? []).some((a) => a.id === creative.asset?.id)
                ? [{ value: creative.asset.id, label: "The current image" }]
                : []),
            ]}
            value={asset}
            onChange={(e) => setAsset(e.target.value)}
          />
        </>
      )}
      <p className={styles.muted}>
        Saving makes a new version; this one is kept as it is. AdVegaX checks the new version again.
      </p>
      <ErrorList error={update.error} />
      <div className={own.actions}>
        <Button type="submit" busy={update.isPending}>
          Save as a new version
        </Button>
        <Button variant="secondary" onClick={onDone} disabled={update.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Decision({
  org,
  setId,
  creative,
}: {
  org: Organization;
  setId: string;
  creative: Creative;
}) {
  const approve = useApprove(org.id, setId);
  const reject = useReject(org.id, setId);
  const [confirm, setConfirm] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const flagged = creative.checks.some((c) => c.severity === "flag");
  return (
    <>
      <ErrorList error={approve.error ?? reject.error} />
      {flagged ? (
        <label>
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />{" "}
          I have checked the flagged wording
        </label>
      ) : null}
      <div className={own.actions}>
        <Button
          busy={approve.isPending}
          disabled={!creative.approvable || (flagged && !confirm)}
          onClick={() => approve.mutate({ id: creative.id, confirm })}
        >
          Approve
        </Button>
        <Button variant="secondary" onClick={() => setRejecting((v) => !v)}>
          Reject
        </Button>
      </div>
      {rejecting ? (
        <form
          className={own.form}
          aria-label={`Reject ${creative.angle}`}
          onSubmit={(e) => {
            e.preventDefault();
            reject.mutate({ id: creative.id, reason: reason.trim() });
          }}
        >
          <TextField
            label="Why is it rejected?"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
            minLength={3}
            maxLength={500}
          />
          <div>
            <Button
              type="submit"
              variant="danger"
              busy={reject.isPending}
              disabled={reason.trim().length < 3}
            >
              Reject this version
            </Button>
          </div>
        </form>
      ) : null}
    </>
  );
}

/** One creative (its newest version): preview, the fixed checks, and what you may do with it. */
export function CreativeCard({
  org,
  setId,
  creative,
}: {
  org: Organization;
  setId: string;
  creative: Creative;
}) {
  const [editing, setEditing] = useState(false);
  const archive = useArchiveCreative(org.id, setId);
  const status = CREATIVE_STATUS[creative.status] ?? {
    label: creative.status,
    tone: "off" as const,
  };
  const blocks = creative.checks.filter((c) => c.severity === "block");
  const flags = creative.checks.filter((c) => c.severity === "flag");
  const manage = canManageCreatives(org.role) && creative.status !== "archived";
  const decide = canApproveCreatives(org.role) && creative.status === "draft";
  return (
    <li className={own.card}>
      <h3>
        {providerName(creative.platform)}: {creative.angle}
      </h3>
      <p>
        <span className={`${styles.status} ${styles[status.tone]}`}>{status.label}</span> · version{" "}
        {creative.version} of {creative.versions.length}
        {creative.decided_at ? ` · decided on ${formatDateTime(creative.decided_at)}` : ""}
      </p>
      {creative.decision_reason ? (
        <p>
          <strong>Why it was rejected:</strong> {creative.decision_reason}
        </p>
      ) : null}
      {editing ? (
        <EditForm org={org} setId={setId} creative={creative} onDone={() => setEditing(false)} />
      ) : creative.platform === "google_ads" ? (
        <GooglePreview content={creative.content as unknown as GoogleContent} />
      ) : (
        <MetaPreview
          org={org}
          content={creative.content as unknown as MetaContent}
          assetId={creative.asset?.id}
        />
      )}
      <section aria-label={`Checks for ${creative.angle}`}>
        {blocks.length === 0 && flags.length === 0 ? (
          <p className={styles.muted}>Passes every AdVegaX check.</p>
        ) : (
          <ul className={own.checks}>
            {blocks.map((c, i) => (
              <li key={`b-${i}`} className={own.block}>
                To fix: {checkText(c)}
              </li>
            ))}
            {flags.map((c, i) => (
              <li key={`f-${i}`} className={own.flag}>
                To check: {checkText(c)}
              </li>
            ))}
          </ul>
        )}
      </section>
      {creative.rationale ? (
        <p>
          <strong>Why:</strong> {creative.rationale}
        </p>
      ) : null}
      {creative.compliance_notes.length ? (
        <>
          <p>
            <strong>The AI&apos;s notes to check</strong> (advice only — AdVegaX&apos;s checks
            decide):
          </p>
          <ul>
            {creative.compliance_notes.map((n, i) => (
              <li key={`n-${i}`}>{n}</li>
            ))}
          </ul>
        </>
      ) : null}
      {!editing && decide ? <Decision org={org} setId={setId} creative={creative} /> : null}
      {!editing && manage ? (
        <div className={own.actions}>
          <Button variant="secondary" onClick={() => setEditing(true)}>
            Edit
          </Button>
          {canApproveCreatives(org.role) ? (
            <Button
              variant="link"
              busy={archive.isPending}
              onClick={() => archive.mutate(creative.id)}
            >
              Archive
            </Button>
          ) : null}
        </div>
      ) : null}
      {archive.error ? <ErrorList error={archive.error} /> : null}
    </li>
  );
}
