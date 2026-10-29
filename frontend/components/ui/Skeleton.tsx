import styles from "./ui.module.css";

/** A grey placeholder line while data loads. Decorative: pair it with a live "Loading…" status. */
export function Skeleton({ size = "full" }: { size?: "short" | "medium" | "full" }) {
  const width =
    size === "short" ? styles.skeletonShort : size === "medium" ? styles.skeletonMedium : "";
  return <span className={`${styles.skeleton} ${width}`} aria-hidden="true" />;
}
