"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ApiError, messageFor } from "@/lib/api/errors";

import styles from "./account.module.css";
import { deviceName as describe } from "./device-name";
import {
  useDeviceSessions,
  useRevokeSession,
  useSignOutEverywhere,
  type DeviceSession,
} from "./queries";

type Notice = { tone: "success" | "error"; text: string; requestId: string | null };

function when(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

function deviceName(s: DeviceSession): string {
  return describe(s.user_agent_summary);
}

function errorNotice(error: unknown): Notice {
  return {
    tone: "error",
    text: messageFor(error),
    requestId: error instanceof ApiError ? error.requestId : null,
  };
}

export function SessionsSection() {
  const sessions = useDeviceSessions();
  const revoke = useRevokeSession();
  const everywhere = useSignOutEverywhere();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [revoking, setRevoking] = useState<DeviceSession | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

  function confirmRevoke() {
    if (!revoking) return;
    const target = revoking;
    revoke.mutate(target.id, {
      onSuccess: () => {
        setRevoking(null);
        setNotice({
          tone: "success",
          text: `Signed out of ${deviceName(target)}.`,
          requestId: null,
        });
      },
      onError: (error) => {
        setRevoking(null);
        setNotice(errorNotice(error));
      },
    });
  }

  function confirmEverywhere() {
    // On success the session becomes "signed out" and RequireAuth sends the person to sign in,
    // with a link back to this page.
    everywhere.mutate(undefined, {
      onError: (error) => {
        setConfirmAll(false);
        setNotice(errorNotice(error));
      },
    });
  }

  const list = sessions.data ?? [];
  const others = list.filter((s) => !s.current);
  // This device first, then the most recently used.
  const ordered = [...list].sort((a, b) =>
    a.current === b.current ? b.last_used_at.localeCompare(a.last_used_at) : a.current ? -1 : 1,
  );

  return (
    <section aria-labelledby="sessions-title" className={styles.section}>
      <h2 id="sessions-title">Where you are signed in</h2>
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.text}
        </Alert>
      ) : null}
      {sessions.error ? <Alert tone="error">{messageFor(sessions.error)}</Alert> : null}
      {sessions.isPending ? <p role="status">Loading your sessions…</p> : null}
      {sessions.data ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>
              {list.length === 1 ? "1 active session" : `${list.length} active sessions`}
            </caption>
            <thead>
              <tr>
                <th scope="col">Device</th>
                <th scope="col">Signed in</th>
                <th scope="col">Last active</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((s) => (
                <tr key={s.id}>
                  <td>
                    {deviceName(s)}
                    {s.current ? <span className={styles.badge}>This device</span> : null}
                  </td>
                  <td>{when(s.created_at)}</td>
                  <td>{when(s.last_used_at)}</td>
                  <td>
                    {s.current ? null : (
                      <Button
                        variant="link"
                        aria-label={`Sign out of ${deviceName(s)}, signed in ${when(s.created_at)}`}
                        onClick={() => setRevoking(s)}
                      >
                        Sign out
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className={styles.panel}>
        <h3>Sign out everywhere</h3>
        <p className={styles.muted}>
          Signs out every device, including this one. Use it if you lost a device or think someone
          else has access to your account.
        </p>
        <Button variant="danger" onClick={() => setConfirmAll(true)}>
          Sign out everywhere
        </Button>
      </div>

      <ConfirmDialog
        open={revoking !== null}
        title="Sign out of this device?"
        confirmLabel="Sign out device"
        busy={revoke.isPending}
        onConfirm={confirmRevoke}
        onCancel={() => setRevoking(null)}
      >
        <p>{revoking ? deviceName(revoking) : ""} will need to sign in again.</p>
      </ConfirmDialog>
      <ConfirmDialog
        open={confirmAll}
        title="Sign out everywhere?"
        confirmLabel="Sign out everywhere"
        busy={everywhere.isPending}
        onConfirm={confirmEverywhere}
        onCancel={() => setConfirmAll(false)}
      >
        <p>
          {others.length
            ? `This signs out this device and ${others.length === 1 ? "1 other session" : `${others.length} other sessions`}.`
            : "This signs out this device."}{" "}
          You will need to sign in again.
        </p>
      </ConfirmDialog>
    </section>
  );
}
