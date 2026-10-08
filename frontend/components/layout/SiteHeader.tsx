import Link from "next/link";

import { AccountNav } from "@/features/auth/AccountNav";

import styles from "./SiteHeader.module.css";

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          AdVegaX
        </Link>
        <AccountNav />
      </div>
    </header>
  );
}
