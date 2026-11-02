"use client";

import { useId, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import ui from "@/components/ui/ui.module.css";
import styles from "@/features/advertising/advertising.module.css";
import type { Organization } from "@/features/organizations/api";
import { canUpdateOrganization } from "@/features/organizations/permissions";
import { ApiError, messageFor } from "@/lib/api/errors";

import { useCreativeRules, useSaveCreativeRules, type CreativeRules } from "./api";
import own from "./creatives.module.css";

const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

function Words({
  label,
  hint,
  value,
  onChange,
  readOnly,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  readOnly: boolean;
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
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/** Settings: the organization's own creative rules (owners and admins change them). */
export function CreativeRulesSettings({ org }: { org: Organization }) {
  const rules = useCreativeRules(org.id);
  const [saved, setSaved] = useState(false);
  if (rules.error) return <Alert tone="error">{messageFor(rules.error)}</Alert>;
  if (!rules.data) return <p role="status">Loading…</p>;
  return (
    <RulesForm
      key={rules.data.updated_at ?? "new"}
      org={org}
      rules={rules.data}
      saved={saved}
      setSaved={setSaved}
    />
  );
}

function RulesForm({
  org,
  rules,
  saved,
  setSaved,
}: {
  org: Organization;
  rules: CreativeRules;
  saved: boolean;
  setSaved: (value: boolean) => void;
}) {
  const save = useSaveCreativeRules(org.id);
  const [terms, setTerms] = useState(rules.prohibited_terms.join("\n"));
  const [caps, setCaps] = useState(rules.allowed_caps.join("\n"));
  const manage = canUpdateOrganization(org.role);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    save.mutate(
      { prohibited_terms: lines(terms), allowed_caps: lines(caps) },
      { onSuccess: () => setSaved(true) },
    );
  };
  return (
    <section aria-labelledby="creative-rules" className={styles.section}>
      <h2 id="creative-rules">Creative rules</h2>
      <p className={styles.muted}>
        Words AdVegaX refuses in your ads, on top of its own list of health and medical claims (
        {rules.base_prohibited_terms.length} terms, such as “
        {rules.base_prohibited_terms.slice(0, 3).join("”, “")}”), and brand words you write in
        capitals.
      </p>
      <form className={own.form} onSubmit={submit} noValidate>
        <Words
          label="Your prohibited words or phrases"
          hint="One per line."
          value={terms}
          onChange={setTerms}
          readOnly={!manage}
        />
        <Words
          label="Words you may write in capitals"
          hint="One per line, e.g. a brand name."
          value={caps}
          onChange={setCaps}
          readOnly={!manage}
        />
        {save.error ? (
          <Alert
            tone="error"
            requestId={save.error instanceof ApiError ? save.error.requestId : null}
          >
            {messageFor(save.error)}
          </Alert>
        ) : null}
        {saved ? <Alert tone="success">Creative rules saved.</Alert> : null}
        {manage ? (
          <div>
            <Button type="submit" busy={save.isPending}>
              Save creative rules
            </Button>
          </div>
        ) : (
          <p className={styles.muted}>Owners and admins can change these.</p>
        )}
      </form>
    </section>
  );
}
