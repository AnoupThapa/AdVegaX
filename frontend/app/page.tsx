import { HomeSession } from "@/features/auth/HomeSession";

import styles from "./page.module.css";

export default function HomePage() {
  return (
    <section className={styles.page} aria-labelledby="home-title">
      <h1 id="home-title">AdVegaX</h1>
      <p className={styles.lead}>
        One place to connect your store, advertising and analytics accounts and grow with
        controlled, auditable decisions.
      </p>
      <HomeSession />
    </section>
  );
}
