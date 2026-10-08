import styles from "./SkipLink.module.css";

export function SkipLink() {
  return (
    <a className={styles.skipLink} href="#main">
      Skip to main content
    </a>
  );
}
