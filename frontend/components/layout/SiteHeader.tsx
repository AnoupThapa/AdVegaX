import Link from "next/link";

import { AccountNav } from "@/features/auth/AccountNav";

import { Container } from "./Layout";
import styles from "./SiteHeader.module.css";

export function SiteHeader() {
  return (
    <header className={styles.header}>
      <Container className={styles.inner}>
        <Link href="/" className={styles.brand}>
          AdVegaX
        </Link>
        <AccountNav />
      </Container>
    </header>
  );
}
