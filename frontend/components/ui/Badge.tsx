import type { ReactNode } from "react";

import styles from "./ui.module.css";

export type BadgeTone = "success" | "warning" | "danger" | "info" | "neutral";

const TONE_CLASS: Record<BadgeTone, string> = {
  success: styles.badgeSuccess ?? "",
  warning: styles.badgeWarning ?? "",
  danger: styles.badgeDanger ?? "",
  info: styles.badgeInfo ?? "",
  neutral: styles.badgeNeutral ?? "",
};

/** A short status. Always carries a text label, so colour is never the only signal. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`${styles.badge} ${TONE_CLASS[tone]}`}>{children}</span>;
}
