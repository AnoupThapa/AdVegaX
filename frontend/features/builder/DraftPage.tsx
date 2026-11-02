"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import ui from "@/components/ui/ui.module.css";
import styles from "@/features/advertising/advertising.module.css";
import { CheckList } from "@/features/changes/ChangesPages";
import own from "@/features/changes/changes.module.css";
import { reasonText } from "@/features/changes/labels";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { canRequestChanges } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import {
  useCleanUp,
  useDraft,
  useGoLive,
  useLaunchDraft,
  useMetaAssets,
  useUpdateDraft,
  useValidateDraft,
  type Draft,
  type DraftPreview,
} from "./api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const COUNTRIES = [
  { code: "AU", name: "Australia" },
  { code: "NZ", name: "New Zealand" },
  { code: "NP", name: "Nepal" },
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "GB", name: "United Kingdom" },
  { code: "CA", name: "Canada" },
  { code: "IE", name: "Ireland" },
  { code: "SG", name: "Singapore" },
];
const MATCHES = [
  { value: "phrase", label: "Phrase match (recommended)" },
  { value: "exact", label: "Exact match" },
  { value: "broad", label: "Broad match" },
];
const STATUS: Record<string, string> = {
  draft: "Being prepared",
  launching: "Being created",
  created: "Created — paused",
  live: "Live",
  failed: "Not fully created — paused",
  archived: "Archived",
};
const BIDDING: Record<string, string> = {
  maximize_conversions: "Maximize conversions (the account records conversions)",
  maximize_clicks: "Maximize clicks (no conversions recorded yet)",
  purchases: "Optimized for purchases (with your pixel)",
  link_clicks: "Optimized for link clicks (no pixel chosen)",
};

function Problems({ error }: { error: unknown }) {
  if (!error) return null;
  const details = error instanceof ApiError ? error.details : [];
  return (
    <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
      {messageFor(error)}
      {details.length ? (
        <ul>
          {details.map((d, i) => (
            <li key={i}>{reasonText(d.reason ?? null)}</li>
          ))}
        </ul>
      ) : null}
    </Alert>
  );
}

/** What the ad will say, exactly as it will be created. */
function AdSummary({ draft }: { draft: Draft }) {
  const content = draft.creative.content as Record<string, unknown>;
  const list = (key: string) => (Array.isArray(content[key]) ? (content[key] as string[]) : []);
  return (
    <section aria-labelledby="ad-summary" className={styles.panel}>
      <h2 id="ad-summary">The ad</h2>
      <p className={styles.muted}>
        Approved creative, version {draft.creative.version} — {draft.creative.angle}
      </p>
      {draft.platform === "google_ads" ? (
        <dl className={styles.facts}>
          <dt>Headlines</dt>
          <dd>{list("headlines").join(" | ")}</dd>
          <dt>Descriptions</dt>
          <dd>{list("descriptions").join(" ")}</dd>
        </dl>
      ) : (
        <dl className={styles.facts}>
          <dt>Primary text</dt>
          <dd>{list("primary_texts")[0]}</dd>
          <dt>Headline</dt>
          <dd>{list("headlines")[0]}</dd>
          <dt>Image</dt>
          <dd>{draft.creative.asset_id ? "Chosen" : "None chosen"}</dd>
        </dl>
      )}
    </section>
  );
}

function EditForm({ draft }: { draft: Draft }) {
  const org = useCurrentOrganization();
  const update = useUpdateDraft(org.id, draft.id);
  const meta = draft.platform === "meta_ads";
  const pages = useMetaAssets(org.id, draft.ad_account_id, "meta-pages", meta);
  const pixels = useMetaAssets(org.id, draft.ad_account_id, "meta-pixels", meta);
  const [name, setName] = useState(draft.name);
  const [budget, setBudget] = useState(draft.daily_budget);
  const [countries, setCountries] = useState<string[]>(draft.locations);
  const [keywords, setKeywords] = useState(draft.keywords.map((k) => k.text).join("\n"));
  const [match, setMatch] = useState(draft.keywords[0]?.match ?? "phrase");
  const [landing, setLanding] = useState(draft.landing_url);
  const [page, setPage] = useState(draft.meta_page_id ?? "");
  const [pixel, setPixel] = useState(draft.meta_pixel_id ?? "");
  const [ageMin, setAgeMin] = useState(String(draft.age_min));
  const [ageMax, setAgeMax] = useState(String(draft.age_max));
  const [declared, setDeclared] = useState(draft.declarations_confirmed);
  const [saved, setSaved] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    update.mutate(
      {
        name,
        daily_budget: budget.trim(),
        locations: countries,
        landing_url: landing.trim(),
        ...(meta
          ? {
              meta_page_id: page || null,
              meta_pixel_id: pixel || null,
              age_min: Number(ageMin),
              age_max: Number(ageMax),
            }
          : {
              keywords: keywords
                .split("\n")
                .map((k) => k.trim())
                .filter(Boolean)
                .map((text) => ({ text, match: match as "phrase" | "exact" | "broad" })),
            }),
        confirm_declarations: declared,
        remove_pixel: meta ? !pixel : false,
      },
      { onSuccess: () => setSaved(true) },
    );
  };
  const toggle = (code: string) =>
    setCountries((now) => (now.includes(code) ? now.filter((c) => c !== code) : [...now, code]));
  return (
    <form className={own.form} onSubmit={submit} noValidate aria-label="Campaign details">
      <TextField
        label="Campaign name"
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <TextField
        label={`Daily budget (${draft.currency})`}
        hint={`About ${formatMoney(draft.monthly_estimate, draft.currency, draft.currency_minor_units)} a month at the saved budget.`}
        inputMode="decimal"
        required
        value={budget}
        onChange={(e) => setBudget(e.target.value)}
      />
      <fieldset className={ui.field}>
        <legend className={ui.label}>Countries</legend>
        {COUNTRIES.map((c) => (
          <label key={c.code} className={own.choice}>
            <input
              type="checkbox"
              checked={countries.includes(c.code)}
              onChange={() => toggle(c.code)}
            />
            {c.name}
          </label>
        ))}
      </fieldset>
      {meta ? (
        <>
          <TextField
            label="Youngest age"
            inputMode="numeric"
            required
            value={ageMin}
            onChange={(e) => setAgeMin(e.target.value)}
          />
          <TextField
            label="Oldest age (65 means 65 and over)"
            inputMode="numeric"
            required
            value={ageMax}
            onChange={(e) => setAgeMax(e.target.value)}
          />
          <SelectField
            label="Facebook Page the ad runs as"
            placeholder={pages.isPending ? "Loading Pages…" : "Choose a Page"}
            options={(pages.data ?? []).map((p) => ({ value: p.id, label: p.name ?? p.id }))}
            value={page}
            onChange={(e) => setPage(e.target.value)}
          />
          {pages.error ? (
            <p className={styles.muted}>
              Your Pages could not be read. Sign in again to allow changes on the Meta connection.
            </p>
          ) : null}
          <SelectField
            label="Pixel (optional: optimize for purchases)"
            placeholder="No pixel: optimize for link clicks"
            options={(pixels.data ?? []).map((p) => ({ value: p.id, label: p.name ?? p.id }))}
            value={pixel}
            onChange={(e) => setPixel(e.target.value)}
          />
        </>
      ) : (
        <>
          <div className={ui.field}>
            <label htmlFor="draft-keywords" className={ui.label}>
              Keywords
            </label>
            <p id="draft-keywords-hint" className={ui.hint}>
              One per line, up to 20.
            </p>
            <textarea
              id="draft-keywords"
              aria-describedby="draft-keywords-hint"
              className={ui.input}
              rows={6}
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
            />
          </div>
          <SelectField
            label="Match type"
            options={MATCHES}
            value={match}
            onChange={(e) => setMatch(e.target.value)}
          />
        </>
      )}
      <TextField
        label="Landing page"
        required
        value={landing}
        onChange={(e) => setLanding(e.target.value)}
      />
      <label className={own.choice}>
        <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
        {meta
          ? "I confirm this ad is not about housing, employment, credit, or social issues, elections or politics (Meta's special ad categories)."
          : "I confirm this campaign contains no EU political advertising (a declaration Google requires)."}
      </label>
      <Problems error={update.error} />
      {saved ? <Alert tone="success">Saved.</Alert> : null}
      <div className={own.actions}>
        <Button type="submit" busy={update.isPending}>
          Save
        </Button>
      </div>
    </form>
  );
}

function Review({ draft }: { draft: Draft }) {
  const org = useCurrentOrganization();
  const validate = useValidateDraft(org.id, draft.id);
  const launch = useLaunchDraft(org.id, draft.id);
  const [preview, setPreview] = useState<DraftPreview | null>(null);
  const [made, setMade] = useState<string | null>(null);
  return (
    <section aria-labelledby="review-title" className={styles.section}>
      <h2 id="review-title">Check and launch</h2>
      <p className={styles.muted}>
        AdVegaX checks everything and the platform tests it without creating anything. Launching
        creates the campaign <strong>paused</strong> after an owner or admin approves it; it goes
        live only with a second approval.
      </p>
      <Problems error={validate.error ?? launch.error} />
      {made ? (
        <Alert tone="success">
          The launch was requested and waits for approval.{" "}
          <Link href={`/orgs/${org.id}/changes/${made}`}>Open it</Link>
        </Alert>
      ) : null}
      {preview ? (
        <>
          <CheckList checks={preview.checks} dryRun={preview.dry_run} />
          <p className={styles.muted}>
            Budget limits: platform minimum{" "}
            {formatMoney(
              preview.budget_limits.platform_minimum,
              draft.currency,
              draft.currency_minor_units,
            )}
            , your maximum{" "}
            {formatMoney(
              preview.budget_limits.organization_maximum,
              draft.currency,
              draft.currency_minor_units,
            )}
            .
          </p>
        </>
      ) : null}
      <div className={own.actions}>
        <Button
          variant="secondary"
          busy={validate.isPending}
          onClick={() => validate.mutate(undefined, { onSuccess: setPreview })}
        >
          Check
        </Button>
        <Button
          busy={launch.isPending}
          disabled={!preview?.passed}
          onClick={() => launch.mutate(undefined, { onSuccess: (a) => setMade(a.id) })}
        >
          Request launch
        </Button>
      </div>
    </section>
  );
}

function AfterLaunch({ draft }: { draft: Draft }) {
  const org = useCurrentOrganization();
  const goLive = useGoLive(org.id, draft.id);
  const cleanUp = useCleanUp(org.id, draft.id);
  const [made, setMade] = useState<string | null>(null);
  const allowed = canRequestChanges(org.role);
  return (
    <section aria-labelledby="after-title" className={styles.panel}>
      <h2 id="after-title">{STATUS[draft.status] ?? draft.status}</h2>
      {draft.status === "created" ? (
        <p>The campaign exists at the platform, paused. Nothing is spent until it goes live.</p>
      ) : null}
      {draft.status === "failed" ? (
        <Alert tone="error">
          {reasonText(draft.error_code)} Everything created is paused, so nothing runs.
        </Alert>
      ) : null}
      {draft.campaign_id ? (
        <p>
          <Link href={`/orgs/${org.id}/advertising/campaigns/${draft.campaign_id}`}>
            Open the campaign under Advertising
          </Link>
        </p>
      ) : null}
      <Problems error={goLive.error ?? cleanUp.error} />
      {made ? (
        <Alert tone="success">
          Requested; it waits for approval.{" "}
          <Link href={`/orgs/${org.id}/changes/${made}`}>Open it</Link>
        </Alert>
      ) : null}
      {allowed && !draft.open_action_id ? (
        <div className={own.actions}>
          {draft.status === "created" ? (
            <Button
              busy={goLive.isPending}
              onClick={() => goLive.mutate(undefined, { onSuccess: (a) => setMade(a.id) })}
            >
              Request Go live
            </Button>
          ) : null}
          {draft.status === "failed" ? (
            <Button
              variant="secondary"
              busy={cleanUp.isPending}
              onClick={() => cleanUp.mutate(undefined, { onSuccess: (a) => setMade(a.id) })}
            >
              Request removal of what was created
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Detail({ draftId }: { draftId: string }) {
  const org = useCurrentOrganization();
  const draft = useDraft(org.id, draftId);
  if (draft.error) {
    if (draft.error instanceof ApiError && draft.error.status === 404) return <NotFound />;
    return <Alert tone="error">{messageFor(draft.error)}</Alert>;
  }
  const d = draft.data;
  if (!d) return <p role="status">Loading campaign…</p>;
  const allowed = canRequestChanges(org.role);
  return (
    <section aria-labelledby="draft-title">
      <p>
        <Link href={`/orgs/${org.id}/strategies/${d.strategy_id}`}>← Strategy</Link>
      </p>
      <PageHeading id="draft-title">{d.name}</PageHeading>
      <p className={styles.source}>
        {d.platform === "meta_ads" ? "Meta Sales campaign" : "Google Ads Search campaign"}
        {d.ad_account_name ? ` in ${d.ad_account_name}` : ""} · reference {d.reference} ·{" "}
        {BIDDING[d.bidding] ?? d.bidding}
      </p>
      {d.open_action_id ? (
        <Alert tone="info">
          A change of this campaign is waiting or on its way.{" "}
          <Link href={`/orgs/${org.id}/changes/${d.open_action_id}`}>Open it</Link>
        </Alert>
      ) : null}
      <AdSummary draft={d} />
      {d.status === "draft" ? (
        <>
          {d.editable && allowed ? <EditForm key={d.version} draft={d} /> : null}
          {!allowed ? (
            <p className={styles.muted}>Owners, admins and managers prepare campaigns.</p>
          ) : null}
          {d.editable && allowed ? <Review draft={d} /> : null}
        </>
      ) : (
        <AfterLaunch draft={d} />
      )}
    </section>
  );
}

function NotFound() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="draft-missing">
      <PageHeading id="draft-missing">Campaign not found</PageHeading>
      <p>This campaign does not exist, or you do not have access to it.</p>
      <p>
        <Link href={`/orgs/${org.id}/strategies`}>Back to strategies</Link>
      </p>
    </section>
  );
}

export function DraftPage() {
  const params = useParams<{ draftId: string }>();
  const id = params.draftId ?? "";
  if (!UUID.test(id)) return <NotFound />;
  return <Detail draftId={id} />;
}
