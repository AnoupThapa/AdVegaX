"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { useToast } from "@/components/ui/Toast";
import ui from "@/components/ui/ui.module.css";
import { formFeedback } from "@/features/auth/form-errors";
import { emailErrors, hasErrors, type FieldErrors } from "@/features/auth/validation";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useCreateInvitation,
  useInvitations,
  useRevokeInvitation,
  type Invitation,
  type Organization,
} from "./api";
import type { Notice } from "./MembersPage";
import { formatDateTime } from "./options";
import styles from "./organizations.module.css";
import {
  ROLE_DESCRIPTIONS,
  ROLE_LABELS,
  assignableRoles,
  roleLabel,
  type Role,
} from "./permissions";

const STATUS_LABELS: Readonly<Record<string, string>> = {
  pending: "Waiting for reply",
  accepted: "Accepted",
  revoked: "Revoked",
  expired: "Expired",
};

type Props = { readonly org: Organization; readonly onNotice: (notice: Notice | null) => void };

/** Invite form and invitation list — shown to owners and admins only. */
export function InvitationsSection({ org, onNotice }: Props) {
  return (
    <section aria-labelledby="invitations-title" className={styles.section}>
      <h2 id="invitations-title">Invitations</h2>
      <InviteForm org={org} onNotice={onNotice} />
      <InvitationsTable org={org} onNotice={onNotice} />
    </section>
  );
}

function InviteForm({ org, onNotice }: Props) {
  const invite = useCreateInvitation(org.id);
  const toast = useToast();
  const roles = assignableRoles(org.role);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [fields, setFields] = useState<FieldErrors>({});
  const emailRef = useRef<HTMLInputElement>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onNotice(null);
    const found: FieldErrors = { email: emailErrors(email) };
    setFields(found);
    if (hasErrors(found)) {
      emailRef.current?.focus();
      return;
    }
    const address = email.trim();
    invite.mutate(
      { email: address, role },
      {
        onSuccess: () => {
          setEmail("");
          setRole("viewer");
          toast.show({
            tone: "success",
            message: `Invitation sent to ${address}. The link in the email is valid for a limited time.`,
          });
        },
        onError: (error) => {
          const feedback = formFeedback(error);
          setFields(feedback.fields);
          onNotice({ tone: "error", message: feedback.message, requestId: feedback.requestId });
          if (feedback.fields.email?.length) emailRef.current?.focus();
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate aria-label="Invite a member" className={styles.panel}>
      <h3>Invite someone</h3>
      <div className={styles.inviteGrid}>
        <TextField
          ref={emailRef}
          label="Email address"
          type="email"
          name="email"
          autoComplete="off"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          errors={fields.email ?? []}
        />
        <SelectField
          label="Role"
          name="role"
          required
          hint={ROLE_DESCRIPTIONS[role]}
          options={roles.map((value) => ({ value, label: ROLE_LABELS[value] }))}
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          errors={fields.role ?? []}
        />
      </div>
      <div className={ui.actions}>
        <Button type="submit" busy={invite.isPending}>
          {invite.isPending ? "Sending…" : "Send invitation"}
        </Button>
      </div>
    </form>
  );
}

function InvitationsTable({ org, onNotice }: Props) {
  const invitations = useInvitations(org.id, true);
  const revoke = useRevokeInvitation(org.id);
  const captionId = useId();

  if (invitations.error) {
    return (
      <Alert
        tone="error"
        requestId={invitations.error instanceof ApiError ? invitations.error.requestId : null}
      >
        {messageFor(invitations.error)}
      </Alert>
    );
  }
  if (!invitations.data) return <p role="status">Loading invitations…</p>;
  if (invitations.data.length === 0) {
    return <p className={styles.muted}>No invitations have been sent yet.</p>;
  }

  function onRevoke(invitation: Invitation) {
    onNotice(null);
    revoke.mutate(invitation.id, {
      onSuccess: () =>
        onNotice({
          tone: "success",
          message: `The invitation to ${invitation.email} was revoked.`,
          requestId: null,
        }),
      onError: (error) =>
        onNotice({
          tone: "error",
          message: messageFor(error),
          requestId: error instanceof ApiError ? error.requestId : null,
        }),
    });
  }

  return (
    <div className={styles.tableWrap} role="region" aria-labelledby={captionId} tabIndex={0}>
      <table className={styles.table}>
        <caption id={captionId}>Sent invitations</caption>
        <thead>
          <tr>
            <th scope="col">Email</th>
            <th scope="col">Role</th>
            <th scope="col">Status</th>
            <th scope="col">Expires</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {invitations.data.map((invitation) => (
            <tr key={invitation.id}>
              <td className={styles.wrap}>{invitation.email}</td>
              <td data-label="Role">{roleLabel(invitation.role)}</td>
              <td data-label="Status">{STATUS_LABELS[invitation.status] ?? invitation.status}</td>
              <td data-label="Expires">
                {invitation.status === "pending" ? formatDateTime(invitation.expires_at) : "—"}
              </td>
              <td>
                {invitation.status === "pending" ? (
                  <Button
                    variant="secondary"
                    busy={revoke.isPending && revoke.variables === invitation.id}
                    onClick={() => onRevoke(invitation)}
                    aria-label={`Revoke invitation to ${invitation.email}`}
                  >
                    Revoke
                  </Button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
