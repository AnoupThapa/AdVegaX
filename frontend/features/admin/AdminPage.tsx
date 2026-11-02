"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { messageFor } from "@/lib/api/errors";

import own from "./admin.module.css";
import {
  useAdminHealth,
  useAdminMe,
  useAdminOrganizations,
  useAdminSettings,
  useAdminUsers,
  useClearSetting,
  useSaveSetting,
  useSetOrganizationStatus,
  useTwoStepEnable,
  useTwoStepSetup,
  useTwoStepVerify,
  type AdminSetting,
} from "./api";

/** The Admin portal (Phase 16): for the people who run this AdVegaX installation. */
export function AdminPage() {
  return (
    <RequireAuth>
      <div className={own.band}>
        <div className={own.bandInner}>
          <PageHeading id="admin-title">Admin</PageHeading>
          <p>Operator area for this AdVegaX installation. Customers never see this page.</p>
        </div>
      </div>
      <div className={own.page}>
        <Gate />
      </div>
    </RequireAuth>
  );
}

function Gate() {
  const me = useAdminMe();
  if (me.error) return <Alert tone="error">{messageFor(me.error)}</Alert>;
  if (!me.data) return <p role="status">Loading…</p>;
  if (!me.data.is_admin) {
    return <p>This page is only for the people who run this AdVegaX installation.</p>;
  }
  if (!me.data.totp_enabled) return <SetUpTwoStep />;
  if (!me.data.verified) return <EnterCode />;
  return <Portal />;
}

function CodeForm({
  label,
  busy,
  error,
  onCode,
}: {
  label: string;
  busy: boolean;
  error: unknown;
  onCode: (code: string) => void;
}) {
  const [code, setCode] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onCode(code);
  };
  return (
    <form aria-label={label} onSubmit={submit} className={styles.panel}>
      <TextField
        label="Code from your authenticator app"
        inputMode="numeric"
        autoComplete="one-time-code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        required
      />
      <Button type="submit" busy={busy}>
        {label}
      </Button>
      {error ? (
        <Alert tone="error">
          That code did not work. Use the newest code, and check your phone&apos;s clock.
        </Alert>
      ) : null}
    </form>
  );
}

function SetUpTwoStep() {
  const setup = useTwoStepSetup();
  const enable = useTwoStepEnable();
  return (
    <section aria-labelledby="two-step">
      <h2 id="two-step">Set up two-step sign-in</h2>
      <p className={styles.muted}>
        The Admin portal needs a code from an authenticator app (Google Authenticator, Microsoft
        Authenticator, 1Password…) each time you sign in.
      </p>
      {!setup.data ? (
        <Button busy={setup.isPending} onClick={() => setup.mutate()}>
          Start
        </Button>
      ) : (
        <>
          <p>
            In your app, add an account and type this key: <strong>{setup.data.secret}</strong>
          </p>
          <p className={styles.muted}>Or open this link on your phone: {setup.data.uri}</p>
          <CodeForm
            label="Switch two-step sign-in on"
            busy={enable.isPending}
            error={enable.error}
            onCode={(code) => enable.mutate(code)}
          />
        </>
      )}
      {setup.error ? <Alert tone="error">{messageFor(setup.error)}</Alert> : null}
    </section>
  );
}

function EnterCode() {
  const verify = useTwoStepVerify();
  return (
    <CodeForm
      label="Open the Admin portal"
      busy={verify.isPending}
      error={verify.error}
      onCode={(code) => verify.mutate(code)}
    />
  );
}

const SECTIONS = [
  { id: "admin-health", label: "System health" },
  { id: "admin-switches", label: "Feature switches" },
  { id: "admin-keys", label: "Keys and connections" },
  { id: "admin-orgs", label: "Organizations" },
  { id: "admin-people", label: "People" },
] as const;

function Portal() {
  return (
    <div className={own.layout}>
      <nav aria-label="Admin sections" className={own.index}>
        <ul>
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>
      <div className={own.content}>
        <p className={own.restart}>
          Saved keys and switches apply the next time AdVegaX starts (on your computer: stop.ps1,
          then start.ps1).
        </p>
        <Health />
        <Switches />
        <Keys />
        <Organizations />
        <People />
      </div>
    </div>
  );
}

function Health() {
  const health = useAdminHealth(true);
  const h = health.data;
  const ok = (good: boolean | undefined) =>
    good ? <Badge tone="success">OK</Badge> : <Badge tone="danger">Not reachable</Badge>;
  return (
    <section aria-labelledby="admin-health" className={own.section}>
      <h2 id="admin-health">System health</h2>
      {health.error ? <Alert tone="error">{messageFor(health.error)}</Alert> : null}
      {h ? (
        <dl className={own.health}>
          <div>
            <dt>Database</dt>
            <dd>{ok(h.database)}</dd>
          </div>
          <div>
            <dt>Background jobs (Redis)</dt>
            <dd>{ok(h.redis)}</dd>
          </div>
          <div>
            <dt>Environment</dt>
            <dd>{h.environment}</dd>
          </div>
          <div>
            <dt>Restart needed</dt>
            <dd>
              {h.restart_needed ? (
                <Badge tone="warning">Yes, a saved change is waiting</Badge>
              ) : (
                <Badge tone="neutral">No</Badge>
              )}
            </dd>
          </div>
        </dl>
      ) : null}
    </section>
  );
}

function useGroups(kind: "switch" | "values") {
  const settings = useAdminSettings(true);
  const groups = new Map<string, AdminSetting[]>();
  for (const s of settings.data ?? []) {
    if ((s.kind === "switch") !== (kind === "switch")) continue;
    groups.set(s.group, [...(groups.get(s.group) ?? []), s]);
  }
  return { error: settings.error, groups, all: settings.data ?? [] };
}

function Switches() {
  const { error, all } = useGroups("switch");
  const save = useSaveSetting();
  const switches = all.filter((s) => s.kind === "switch");
  return (
    <section aria-labelledby="admin-switches" className={own.section}>
      <h2 id="admin-switches">Feature switches</h2>
      <p className={own.muted}>Leave a platform off until its keys are entered below.</p>
      {error ? <Alert tone="error">{messageFor(error)}</Alert> : null}
      <ul className={own.switches} aria-label="Feature switches">
        {switches.map((s) => {
          const on = s.hint === "on";
          return (
            <li key={s.name}>
              <span className={own.switchText}>
                <span className={own.rowLabel}>{s.label}</span>
                <span className={own.muted}>{SOURCE[s.source] ?? s.source}</span>
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                aria-label={s.label}
                className={own.switch}
                disabled={save.isPending}
                onClick={() => save.mutate({ name: s.name, value: on ? "false" : "true" })}
              >
                <span className={own.switchState}>{on ? "On" : "Off"}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {save.error ? <Alert tone="error">{messageFor(save.error)}</Alert> : null}
    </section>
  );
}

function Keys() {
  const { error, groups } = useGroups("values");
  return (
    <section aria-labelledby="admin-keys" className={own.section}>
      <h2 id="admin-keys">Keys and connections</h2>
      <p className={own.muted}>
        Keys are stored encrypted and never shown again, only whether they are set and their last
        four characters.
      </p>
      {error ? <Alert tone="error">{messageFor(error)}</Alert> : null}
      {[...groups.entries()].map(([group, entries]) => (
        <div key={group} className={own.group}>
          <h3>{group}</h3>
          <ul className={own.rows} aria-label={group}>
            {entries.map((s) => (
              <SettingRow key={s.name} setting={s} />
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

const SOURCE: Record<string, string> = {
  portal: "saved here",
  settings_file: "from the settings file",
  default: "default",
};

function SettingRow({ setting }: { setting: AdminSetting }) {
  const save = useSaveSetting();
  const clear = useClearSetting();
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(
      { name: setting.name, value },
      {
        onSuccess: () => {
          setValue("");
          setOpen(false);
        },
      },
    );
  };
  return (
    <li className={own.row}>
      <div className={own.rowHead}>
        <span className={own.rowLabel}>{setting.label}</span>
        <span className={own.rowState}>
          {setting.set ? (
            <Badge tone="success">{setting.hint || "Set"}</Badge>
          ) : (
            <Badge tone="neutral">Not set</Badge>
          )}
          <span className={own.muted}>{SOURCE[setting.source] ?? setting.source}</span>
        </span>
        <Button
          variant="secondary"
          aria-expanded={open}
          aria-label={`${open ? "Close" : "Change"} ${setting.label}`}
          onClick={() => setOpen(!open)}
        >
          {open ? "Close" : setting.set ? "Change" : "Add"}
        </Button>
      </div>
      {open ? (
        <form aria-label={setting.label} onSubmit={submit} className={own.rowForm}>
          <TextField
            label={setting.set ? `New ${setting.label}` : setting.label}
            type={setting.kind === "secret" ? "password" : "text"}
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
          />
          <div className={own.formActions}>
            <Button type="submit" busy={save.isPending}>
              Save
            </Button>
            {setting.source === "portal" ? (
              <Button
                variant="link"
                busy={clear.isPending}
                onClick={() => clear.mutate(setting.name)}
              >
                Use the settings file instead
              </Button>
            ) : null}
          </div>
        </form>
      ) : null}
      {save.error ? <Alert tone="error">{messageFor(save.error)}</Alert> : null}
    </li>
  );
}

function Organizations() {
  const orgs = useAdminOrganizations(true);
  const change = useSetOrganizationStatus();
  return (
    <section aria-labelledby="admin-orgs" className={own.section}>
      <h2 id="admin-orgs">Organizations</h2>
      {orgs.error ? <Alert tone="error">{messageFor(orgs.error)}</Alert> : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption>Organizations</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Status</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>
            {orgs.data?.map((o) => (
              <tr key={o.id}>
                <th scope="row">{o.name}</th>
                <td>{o.status === "active" ? "Active" : "Suspended"}</td>
                <td>
                  <Button
                    variant="secondary"
                    busy={change.isPending}
                    onClick={() =>
                      change.mutate({
                        id: o.id,
                        status: o.status === "active" ? "suspended" : "active",
                      })
                    }
                  >
                    {o.status === "active" ? `Suspend ${o.name}` : `Reactivate ${o.name}`}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function People() {
  const users = useAdminUsers(true);
  return (
    <section aria-labelledby="admin-people" className={own.section}>
      <h2 id="admin-people">People</h2>
      {users.error ? <Alert tone="error">{messageFor(users.error)}</Alert> : null}
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption>People</caption>
          <thead>
            <tr>
              <th scope="col">Email</th>
              <th scope="col">Name</th>
              <th scope="col">Status</th>
              <th scope="col">Administrator</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id}>
                <th scope="row">{u.email}</th>
                <td>{u.display_name ?? "—"}</td>
                <td>{u.status}</td>
                <td>{u.is_admin ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
