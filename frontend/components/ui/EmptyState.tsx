import type { ReactNode } from "react";

import styles from "./ui.module.css";

type EmptyStateProps = {
  readonly title: string;
  readonly children?: ReactNode;
  /** The next step, for example a link or button. */
  readonly action?: ReactNode;
};

/** For lists and pages with nothing in them yet: says why and what to do next. */
export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <p className={styles.emptyTitle}>{title}</p>
      {children ? <p className={styles.emptyBody}>{children}</p> : null}
      {action}
    </div>
  );
}
