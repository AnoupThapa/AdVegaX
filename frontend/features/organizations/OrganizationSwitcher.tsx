"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import type { SessionUser } from "@/features/auth/session";

import styles from "./OrganizationSwitcher.module.css";
import { roleLabel } from "./permissions";

/**
 * Header menu listing the user's organizations (from `GET /auth/me`) — a disclosure button
 * with plain links, operable by keyboard; Escape or a click outside closes it.
 */
export function OrganizationSwitcher({ user }: { user: SessionUser }) {
  const params = useParams<{ organizationId?: string }>();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const memberships = user.memberships ?? [];
  const current = memberships.find((m) => m.organization_id === params?.organizationId);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    }
    function onPointer(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  if (!user.email_verified && memberships.length === 0) return null;

  return (
    <div ref={wrapper} className={styles.switcher}>
      <button
        ref={button}
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="visually-hidden">Organization: </span>
        <span className={styles.label}>{current?.organization_name ?? "Organizations"}</span>
        <span aria-hidden="true" className={styles.chevron}>
          ▾
        </span>
      </button>
      <div id={menuId} hidden={!open} className={styles.menu}>
        {memberships.length ? (
          <ul className={styles.list} aria-label="Your organizations">
            {memberships.map((m) => {
              const isCurrent = m.organization_id === current?.organization_id;
              return (
                <li key={m.organization_id}>
                  <Link
                    href={`/orgs/${m.organization_id}`}
                    aria-current={isCurrent ? "true" : undefined}
                    onClick={() => setOpen(false)}
                    className={isCurrent ? styles.current : styles.item}
                  >
                    <span className={styles.name}>{m.organization_name}</span>
                    <span className={styles.role}>{roleLabel(m.role)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className={styles.empty}>You are not in any organization yet.</p>
        )}
        {user.email_verified ? (
          <Link href="/orgs/new" className={styles.create} onClick={() => setOpen(false)}>
            Create an organization
          </Link>
        ) : null}
      </div>
    </div>
  );
}
