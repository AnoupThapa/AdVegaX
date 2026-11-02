"use client";

import { useEffect, useRef, type ReactNode } from "react";

import styles from "./ui.module.css";

type PageCardProps = {
  readonly title: string;
  readonly children: ReactNode;
  readonly footer?: ReactNode;
};

/** A centred single-task page (sign in, sign up, …). Focus moves to the heading on arrival. */
export function PageCard({ title, children, footer }: PageCardProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section className={styles.cardPage} aria-labelledby="page-title">
      <div className={styles.card}>
        <h1 id="page-title" ref={heading} tabIndex={-1} className={styles.cardTitle}>
          {title}
        </h1>
        {children}
      </div>
      {footer ? <div className={styles.cardFooter}>{footer}</div> : null}
    </section>
  );
}
