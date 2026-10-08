import Link from "next/link";

import styles from "./page.module.css";

export default function NotFound() {
  return (
    <section className={styles.page} aria-labelledby="not-found-title">
      <h1 id="not-found-title">Page not found</h1>
      <p className={styles.lead}>This page does not exist, or you do not have access to it.</p>
      <p>
        <Link href="/">Go to the home page</Link>
      </p>
    </section>
  );
}
