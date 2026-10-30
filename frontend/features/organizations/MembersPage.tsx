"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { PageHeading } from "@/components/ui/PageHeading";

import { InvitationsSection } from "./InvitationsSection";
import { MembersTable } from "./MembersTable";
import { useCurrentOrganization } from "./OrganizationShell";
import styles from "./organizations.module.css";
import { canManageMembers } from "./permissions";

export type Notice = { tone: "error" | "success"; message: string; requestId: string | null };

export function MembersPage() {
  const org = useCurrentOrganization();
  // One announcement area for the whole page, so results are read out wherever the action was.
  const [notice, setNotice] = useState<Notice | null>(null);
  return (
    <section aria-labelledby="members-title">
      <PageHeading id="members-title">Members</PageHeading>
      {canManageMembers(org.role) ? null : (
        <p className={styles.muted}>Only owners and admins can invite or change members.</p>
      )}
      {notice ? (
        <Alert tone={notice.tone} requestId={notice.requestId}>
          {notice.message}
        </Alert>
      ) : null}
      <MembersTable org={org} onNotice={setNotice} />
      {canManageMembers(org.role) ? <InvitationsSection org={org} onNotice={setNotice} /> : null}
    </section>
  );
}
