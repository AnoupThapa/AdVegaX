import type { ReactNode } from "react";

import styles from "./ui.module.css";

type AlertProps = {
  readonly tone: "error" | "success" | "info";
  readonly children: ReactNode;
  readonly requestId?: string | null;
};

/** Errors are announced immediately (role="alert"); other messages politely (role="status"). */
export function Alert({ tone, children, requestId }: AlertProps) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`${styles.alert} ${styles[tone]}`}>
      <div>{children}</div>
      {requestId ? <p className={styles.requestId}>Reference: {requestId}</p> : null}
    </div>
  );
}
