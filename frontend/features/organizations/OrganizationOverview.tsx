"use client";

import Link from "next/link";

import { PageHeading } from "@/components/ui/PageHeading";
import { OverviewAutopilot } from "@/features/autopilot/AutopilotSettings";
import { RecentChanges } from "@/features/changes/RecentChanges";
import dash from "@/features/overview/dashboard.module.css";
import { OverviewFigures } from "@/features/overview/OverviewFigures";
import { OverviewRecommendations } from "@/features/recommendations/RecommendationsPages";

import { useCurrentOrganization } from "./OrganizationShell";
import styles from "./organizations.module.css";
import { canManageMembers, roleLabel } from "./permissions";

export function OrganizationOverview() {
  const org = useCurrentOrganization();
  return (
    <section aria-labelledby="org-title">
      <div className={dash.head}>
        <PageHeading id="org-title">{org.name}</PageHeading>
        <p className={styles.muted}>
          Your role: <span className={styles.badge}>{roleLabel(org.role)}</span>
        </p>
      </div>
      <OverviewAutopilot org={org} />
      <OverviewFigures org={org}>
        <div className={dash.work}>
          <OverviewRecommendations org={org} />
          <RecentChanges org={org} />
        </div>
      </OverviewFigures>
      <div className={dash.team}>
        <h2>Your team</h2>
        <p>
          {canManageMembers(org.role)
            ? "Invite people to work with you and choose what each of them can do."
            : "See who else works in this organization."}
        </p>
        <p>
          <Link href={`/orgs/${org.id}/members`}>
            {canManageMembers(org.role) ? "Manage members" : "View members"}
          </Link>
        </p>
      </div>
    </section>
  );
}
