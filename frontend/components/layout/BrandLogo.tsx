import styles from "./BrandLogo.module.css";

/**
 * The AdVegaX lockup (mark + wordmark) from the brand files in /public/brand.
 * `tone="auto"` follows the colour scheme (navy strokes on paper, ivory strokes in dark mode);
 * `tone="onDark"` is for the always-navy bands. The wordmark carries the accessible name.
 */
export function BrandLogo({ tone = "auto" }: { tone?: "auto" | "onDark" }) {
  const dark = tone === "onDark";
  return (
    <span className={styles.logo}>
      <picture>
        {dark ? null : (
          <source srcSet="/brand/mark-dark.webp" media="(prefers-color-scheme: dark)" />
        )}
        <img
          className={styles.mark}
          src={dark ? "/brand/mark-dark.webp" : "/brand/mark.webp"}
          width={155}
          height={96}
          alt=""
        />
      </picture>
      <picture>
        {dark ? null : (
          <source srcSet="/brand/wordmark-dark.webp" media="(prefers-color-scheme: dark)" />
        )}
        <img
          className={styles.wordmark}
          src={dark ? "/brand/wordmark-dark.webp" : "/brand/wordmark.webp"}
          width={304}
          height={60}
          alt="AdVegaX"
        />
      </picture>
    </span>
  );
}
