"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { Icon, type IconName } from "@/components/ui/Icon";
import { useAgency } from "@/features/agency/api";

import type { Organization } from "./api";
import styles from "./OrganizationNav.module.css";

type Section = { readonly href: string; readonly label: string; readonly icon: IconName };
type Group = { readonly title: string | null; readonly sections: readonly Section[] };

/** Grouped by what the person is doing, not by the order the features were built. */
const GROUPS: readonly Group[] = [
  { title: null, sections: [{ href: "", label: "Overview", icon: "overview" }] },
  {
    title: "Performance",
    sections: [
      { href: "/reports", label: "Reports", icon: "reports" },
      { href: "/funnel", label: "Funnel", icon: "funnel" },
      { href: "/analytics", label: "Analytics", icon: "analytics" },
    ],
  },
  {
    title: "Marketing",
    sections: [
      { href: "/advertising", label: "Advertising", icon: "advertising" },
      { href: "/strategies", label: "Strategies", icon: "strategies" },
      { href: "/creatives", label: "Creatives", icon: "creatives" },
      { href: "/recommendations", label: "Recommendations", icon: "recommendations" },
      { href: "/changes", label: "Changes", icon: "changes" },
    ],
  },
  {
    title: "Data",
    sections: [
      { href: "/stores", label: "Stores", icon: "stores" },
      { href: "/connections", label: "Connections", icon: "connections" },
    ],
  },
  {
    title: "Organization",
    sections: [
      { href: "/members", label: "Members", icon: "members" },
      { href: "/settings", label: "Settings", icon: "settings" },
      { href: "/billing", label: "Billing", icon: "billing" },
    ],
  },
];

const CLIENTS: Section = { href: "/clients", label: "Clients", icon: "clients" };

function isCurrent(pathname: string, href: string, section: Section): boolean {
  // Sub-pages (for example one connection) keep their section highlighted.
  return pathname === href || (section.href !== "" && pathname.startsWith(`${href}/`));
}

export function OrganizationNav({ org }: { org: Organization }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const base = `/orgs/${org.id}`;
  const agency = useAgency(org.id);
  const hasClients = agency.data?.clients.some((g) => g.status === "active") ?? false;
  const groups = hasClients
    ? GROUPS.map((g) =>
        g.title === "Organization" ? { ...g, sections: [CLIENTS, ...g.sections] } : g,
      )
    : GROUPS;
  const current = groups
    .flatMap((g) => g.sections)
    .find((s) => isCurrent(pathname, `${base}${s.href}`, s));

  return (
    <nav aria-label="Organization" className={styles.nav}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls="organization-menu"
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name={open ? "close" : "menu"} />
        <span className={styles.toggleText}>
          <span className={styles.toggleOrg}>{org.name}</span>
          <span className={styles.toggleCurrent}>{current?.label ?? "Menu"}</span>
        </span>
      </button>
      <p className={styles.title}>{org.name}</p>
      <div id="organization-menu" className={styles.panel} data-open={open}>
        {groups.map((group, index) => (
          <div key={group.title ?? index} className={styles.group}>
            {group.title ? <p className={styles.groupTitle}>{group.title}</p> : null}
            <ul className={styles.list}>
              {group.sections.map((section) => {
                const href = `${base}${section.href}`;
                const here = isCurrent(pathname, href, section);
                return (
                  <li key={section.label}>
                    <Link
                      href={href}
                      aria-current={here ? "page" : undefined}
                      className={here ? styles.current : styles.link}
                      onClick={() => setOpen(false)}
                    >
                      <Icon name={section.icon} size={18} />
                      {section.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
