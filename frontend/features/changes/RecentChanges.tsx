"use client";

import Link from "next/link";

import dash from "@/features/overview/dashboard.module.css";
import type { Organization } from "@/features/organizations/api";

import { useActions } from "./api";
import { Status, moneyOf } from "./ChangesPages";
import { describe } from "./labels";

const ago = (value: string) =>
  new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );

/** The Overview's activity column: the latest changes to ad accounts, newest first. */
export function RecentChanges({ org }: { org: Organization }) {
  const actions = useActions(org.id, "");
  if (!actions.data) return null;
  const latest = actions.data.slice(0, 6);
  return (
    <section aria-labelledby="overview-activity" className={dash.panel}>
      <h2 id="overview-activity" className={dash.panelTitle}>
        Recent changes
      </h2>
      {latest.length === 0 ? (
        <p className={dash.panelLead}>
          No changes yet. Approved advice and changes you make to campaigns are listed here.
        </p>
      ) : (
        <ol className={dash.feed} aria-label="Recent changes">
          {latest.map((a) => (
            <li key={a.id} className={dash.feedItem}>
              <Link href={`/orgs/${org.id}/changes/${a.id}`} className={dash.itemTitle}>
                {describe(a, moneyOf(a))}
              </Link>
              <span className={dash.itemMeta}>
                {a.campaign ? `${a.campaign.name} · ` : ""}
                <time dateTime={a.updated_at}>{ago(a.updated_at)}</time>
              </span>
              <span className={dash.itemSide}>
                <Status status={a.status} />
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className={dash.panelFoot}>
        <Link href={`/orgs/${org.id}/changes`}>See all changes</Link>
      </p>
    </section>
  );
}
