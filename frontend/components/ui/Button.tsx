import type { ButtonHTMLAttributes } from "react";

import styles from "./ui.module.css";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  readonly variant?: "primary" | "secondary" | "link";
  /** Shows a busy state and blocks repeat submissions. */
  readonly busy?: boolean;
};

export function Button({
  variant = "primary",
  busy = false,
  disabled,
  children,
  type = "button",
  className,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      className={[styles.button, styles[variant], className].filter(Boolean).join(" ")}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
    >
      {children}
    </button>
  );
}
