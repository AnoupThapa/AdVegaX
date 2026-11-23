"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { SelectField } from "@/components/ui/SelectField";
import { useSession } from "@/features/auth/session";
import { ApiError, messageFor } from "@/lib/api/errors";

import {
  useChangeMemberRole,
  useMembers,
  useRemoveMember,
  type Member,
  type Organization,
} from "./api";
import type { Notice } from "./MembersPage";
import { formatDateTime } from "./options";
import styles from "./organizations.module.css";
import { ROLE_LABELS, assignableRoles, canManageMember, roleLabel, type Role } from "./permissions";

const STATUS_LABELS: Readonly<Record<string, string>> = {
  active: "Active",
  suspended: "Suspended",
};

type Props = { readonly org: Organization; readonly onNotice: (notice: Notice | null) => void };

function errorNotice(error: unknown): Notice {
  return {
    tone: "error",
    message: messageFor(error),
    requestId: error instanceof ApiError ? error.requestId : null,
  };
}

function memberName(member: Member): string {
  return member.display_name || member.email;
}

export function MembersTable({ org, onNotice }: Props) {
  const members = useMembers(org.id);
  const remove = useRemoveMember(org.id);
  const { user } = useSession();
  const router = useRouter();
  const [removing, setRemoving] = useState<Member | null>(null);
  const captionId = useId();

  if (members.error) {
    return (
      <Alert
        tone="error"
        requestId={members.error instanceof ApiError ? members.error.requestId : null}
      >
        {messageFor(members.error)}
      </Alert>
    );
  }
  if (!members.data) return <p role="status">Loading members…</p>;

  const removingSelf = removing !== null && removing.user_id === user?.id;

  function confirmRemove() {
    if (!removing) return;
    const target = removing;
    const self = target.user_id === user?.id;
    remove.mutate(target.id, {
      onSuccess: () => {
        setRemoving(null);
        if (self) {
          router.push("/");
          return;
        }
        onNotice({
          tone: "success",
          message: `${memberName(target)} was removed from the organization.`,
          requestId: null,
        });
      },
      onError: (error) => {
        setRemoving(null);
        onNotice(errorNotice(error));
      },
    });
  }

  return (
    <>
      {/* A keyboard-focusable, labelled region, so the table can be scrolled without a mouse. */}
      <div className={styles.tableWrap} role="region" aria-labelledby={captionId} tabIndex={0}>
        <table className={styles.table}>
          <caption id={captionId}>
            {members.data.length === 1 ? "1 member" : `${members.data.length} members`}
          </caption>
          <thead>
            <tr>
              <th scope="col">Member</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Joined</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {members.data.map((member) => (
              <MemberRow
                key={member.id}
                org={org}
                member={member}
                isSelf={member.user_id === user?.id}
                onNotice={onNotice}
                onRemove={() => {
                  onNotice(null);
                  setRemoving(member);
                }}
              />
            ))}
          </tbody>
        </table>
      </div>
      <ConfirmDialog
        open={removing !== null}
        title={removingSelf ? "Leave this organization?" : "Remove this member?"}
        confirmLabel={removingSelf ? "Leave organization" : "Remove member"}
        busy={remove.isPending}
        onConfirm={confirmRemove}
        onCancel={() => setRemoving(null)}
      >
        {removing ? (
          <p>
            {removingSelf ? (
              <>
                You will lose access to <strong>{org.name}</strong> straight away. Someone with the
                Owner or Admin role would need to invite you again.
              </>
            ) : (
              <>
                <strong>{memberName(removing)}</strong> will lose access to{" "}
                <strong>{org.name}</strong> straight away. You can invite them again later.
              </>
            )}
          </p>
        ) : null}
      </ConfirmDialog>
    </>
  );
}

type RowProps = {
  readonly org: Organization;
  readonly member: Member;
  readonly isSelf: boolean;
  readonly onNotice: (notice: Notice | null) => void;
  readonly onRemove: () => void;
};

function MemberRow({ org, member, isSelf, onNotice, onRemove }: RowProps) {
  const changeRole = useChangeMemberRole(org.id);
  const [role, setRole] = useState(member.role);
  const manageable = canManageMember(org.role, member.role);
  const options = assignableRoles(org.role).map((value: Role) => ({
    value,
    label: ROLE_LABELS[value],
  }));
  const name = memberName(member);

  function saveRole() {
    onNotice(null);
    changeRole.mutate(
      { memberId: member.id, role: role as Role },
      {
        onSuccess: (updated) =>
          onNotice({
            tone: "success",
            message: `${name} is now ${roleLabel(updated.role)}.`,
            requestId: null,
          }),
        onError: (error) => {
          setRole(member.role);
          onNotice(errorNotice(error));
        },
      },
    );
  }

  return (
    <tr>
      <td>
        <span className={styles.who}>
          <span>
            {member.display_name || member.email}
            {isSelf ? " (you)" : null}
          </span>
          {member.display_name ? <span className={styles.email}>{member.email}</span> : null}
        </span>
      </td>
      <td data-label="Role">
        {manageable ? (
          <div className={styles.rowActions}>
            <SelectField
              className={styles.inlineField}
              label={`Role for ${name}`}
              hideLabel
              options={options}
              value={role}
              onChange={(e) => setRole(e.target.value)}
            />
            {role !== member.role ? (
              <Button
                variant="secondary"
                busy={changeRole.isPending}
                onClick={saveRole}
                aria-label={`Save role for ${name}`}
              >
                Save role
              </Button>
            ) : null}
          </div>
        ) : (
          <span className={styles.badge}>{roleLabel(member.role)}</span>
        )}
      </td>
      <td data-label="Status">{STATUS_LABELS[member.status] ?? member.status}</td>
      <td data-label="Joined">{formatDateTime(member.created_at)}</td>
      <td>
        {manageable ? (
          <Button
            variant="secondary"
            onClick={onRemove}
            aria-label={isSelf ? "Leave organization" : `Remove ${name}`}
          >
            {isSelf ? "Leave" : "Remove"}
          </Button>
        ) : null}
      </td>
    </tr>
  );
}
