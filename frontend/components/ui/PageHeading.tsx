"use client";

import { useEffect, useRef, type ReactNode } from "react";

import styles from "./ui.module.css";

/**
 * The page's `<h1>`. Focus moves here when the page opens, so screen-reader and keyboard users
 * start at the new content after client-side navigation (PHASE_01C_PLAN §8).
 */
export function PageHeading({ children, id }: { children: ReactNode; id?: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <h1 ref={heading} id={id} tabIndex={-1} className={styles.pageHeading}>
      {children}
    </h1>
  );
}
