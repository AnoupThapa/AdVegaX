"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { TextField } from "@/components/ui/TextField";
import page from "@/features/account/account.module.css";
import styles from "@/features/advertising/advertising.module.css";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { messageFor } from "@/lib/api/errors";

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
      <div className={page.page}>
        <PageHeading id="admin-title">Admin</PageHeading>
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

function Portal() {
  return (
    <>
      <Alert tone="info">
        Saved keys and switches apply the next time AdVegaX starts (on your computer: stop.ps1, then
        start.ps1).
      </Alert>
      <Health />
      <Settings />
      <Organizations />
      <People />
    </>
  );
}

function Health() {
  const health = useAdminHealth(true);
  const h = health.data;
  return (
    <section aria-labelledby="admin-health" className={styles.section}>
      <h2 id="admin-health">System health</h2>
      {health.error ? <Alert tone="error">{messageFor(health.error)}</Alert> : null}
      {h ? (
        <dl className={styles.facts}>
          <dt>Database</dt>
          <dd>{h.database ? "OK" : "Not reachable"}</dd>
          <dt>Background jobs (Redis)</dt>
          <dd>{h.redis ? "OK" : "Not reachable"}</dd>
          <dt>Environment</dt>
          <dd>{h.environment}</dd>
          <dt>Restart needed</dt>
          <dd>{h.restart_needed ? "Yes — a saved change is waiting" : "No"}</dd>
        </dl>
      ) : null}
    </section>
  );
}

function Settings() {
  const settings = useAdminSettings(true);
  const groups = new Map<string, AdminSetting[]>();
  for (const s of settings.data ?? []) groups.set(s.group, [...(groups.get(s.group) ?? []), s]);
  return (
    <section aria-labelledby="admin-settings" className={styles.section}>
      <h2 id="admin-settings">Keys, connections and switches</h2>
      <p className={styles.muted}>
        Keys are stored encrypted and never shown again — only whether they are set and their last
        four characters. Leave a platform off until its keys are entered.
      </p>
      {settings.error ? <Alert tone="error">{messageFor(settings.error)}</Alert> : null}
      {[...groups.entries()].map(([group, entries]) => (
        <div key={group} className={styles.panel}>
          <h3>{group}</h3>
          <ul className={styles.list} aria-label={group}>
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
  const state = setting.set ? (setting.hint ?? "set") : "not set";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate({ name: setting.name, value }, { onSuccess: () => setValue("") });
  };
  return (
    <li className={styles.card}>
      <p>
        <strong>{setting.label}</strong> — {state}{" "}
        <span className={styles.muted}>({SOURCE[setting.source] ?? setting.source})</span>
      </p>
      {setting.kind === "switch" ? (
        <Button
          variant="secondary"
          busy={save.isPending}
          onClick={() =>
            save.mutate({ name: setting.name, value: setting.hint === "on" ? "false" : "true" })
          }
        >
          {setting.hint === "on" ? `Switch off: ${setting.label}` : `Switch on: ${setting.label}`}
        </Button>
      ) : (
        <form aria-label={setting.label} onSubmit={submit}>
          <TextField
            label={setting.set ? `New ${setting.label}` : setting.label}
            type={setting.kind === "secret" ? "password" : "text"}
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
          />
          <Button type="submit" busy={save.isPending}>
            Save
          </Button>
        </form>
      )}
      {setting.source === "portal" ? (
        <Button variant="link" busy={clear.isPending} onClick={() => clear.mutate(setting.name)}>
          Use the settings file instead
        </Button>
      ) : null}
      {save.error ? <Alert tone="error">{messageFor(save.error)}</Alert> : null}
    </li>
  );
}

function Organizations() {
  const orgs = useAdminOrganizations(true);
  const change = useSetOrganizationStatus();
  return (
    <section aria-labelledby="admin-orgs" className={styles.section}>
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
    <section aria-labelledby="admin-people" className={styles.section}>
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
