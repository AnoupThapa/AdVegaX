"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { useAdminMe } from "@/features/admin/api";

import styles from "./AccountMenu.module.css";
import type { SessionUser } from "./session";

/**
 * The signed-in person's menu in the header: who they are, their account security and, for the
 * people who run this installation, the Admin portal. A disclosure button with plain links,
 * operable by keyboard; Escape or a click outside closes it.
 */
export function AccountMenu({ user }: { user: SessionUser }) {
  const admin = useAdminMe();
  const [open, setOpen] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const name = user.display_name || user.email;

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

  return (
    <div ref={wrapper} className={styles.wrapper}>
      <button
        ref={button}
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.avatar} aria-hidden="true">
          {name.trim().charAt(0).toUpperCase()}
        </span>
        <span className={styles.name}>{name}</span>
        <span className="visually-hidden"> (account menu)</span>
      </button>
      <div id={menuId} hidden={!open} className={styles.menu}>
        <p className={styles.who}>
          <span className={styles.whoName}>{name}</span>
          {user.display_name ? <span className={styles.whoEmail}>{user.email}</span> : null}
        </p>
        <ul className={styles.list}>
          <li>
            <Link href="/account/security" className={styles.item} onClick={() => setOpen(false)}>
              Account security
            </Link>
          </li>
          {admin.data?.is_admin ? (
            <li>
              <Link href="/admin" className={styles.item} onClick={() => setOpen(false)}>
                Admin portal
              </Link>
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
