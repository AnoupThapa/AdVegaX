import type { ElementType, ReactNode } from "react";

import styles from "./layout.module.css";

type Gap = 2 | 3 | 4 | 6 | 8;

const STACK_GAP: Record<Gap, string | undefined> = {
  2: styles.gap2,
  3: styles.gap3,
  4: styles.gap4,
  6: styles.gap6,
  8: styles.gap8,
};

type BoxProps = {
  readonly children: ReactNode;
  /** The element to render; a landmark or list where one is meant. */
  readonly as?: ElementType;
  readonly className?: string | undefined;
};

const join = (...names: (string | undefined | false)[]) => names.filter(Boolean).join(" ");

/** Centres content, caps its width and applies the responsive side padding. */
export function Container({
  children,
  as: Tag = "div",
  size = "default",
  className,
}: BoxProps & { readonly size?: "default" | "narrow" }) {
  return (
    <Tag className={join(styles.container, size === "narrow" && styles.narrow, className)}>
      {children}
    </Tag>
  );
}

/** Children one under another with an even gap (space tokens 2, 3, 4, 6 or 8). */
export function Stack({
  children,
  as: Tag = "div",
  gap = 4,
  className,
}: BoxProps & { readonly gap?: Gap }) {
  return <Tag className={join(styles.stack, STACK_GAP[gap], className)}>{children}</Tag>;
}

/** Items in a row that wraps instead of overflowing; optionally pushed apart or aligned. */
export function Cluster({
  children,
  as: Tag = "div",
  gap = 3,
  spread = false,
  align = "center",
  className,
}: BoxProps & {
  readonly gap?: 2 | 3 | 4;
  readonly spread?: boolean;
  readonly align?: "start" | "center" | "end";
}) {
  return (
    <Tag
      className={join(
        styles.cluster,
        gap === 2 && styles.clusterGap2,
        gap === 4 && styles.clusterGap4,
        spread && styles.spread,
        align === "start" && styles.alignStart,
        align === "end" && styles.alignEnd,
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** Equal columns that wrap by available width. `min` is the narrowest a column may get, in rem. */
export function Grid({
  children,
  as: Tag = "div",
  min = 16,
  className,
}: BoxProps & { readonly min?: 12 | 16 | 20 }) {
  return (
    <Tag
      className={join(
        styles.grid,
        min === 12 && styles.gridMin12,
        min === 20 && styles.gridMin20,
        className,
      )}
    >
      {children}
    </Tag>
  );
}
