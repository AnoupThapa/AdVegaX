"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "./Button";
import styles from "./ui.module.css";

type ConfirmDialogProps = {
  readonly open: boolean;
  readonly title: string;
  readonly children: ReactNode;
  readonly confirmLabel: string;
  readonly busy?: boolean;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
};

/**
 * A confirmation step for actions that cannot be undone (PHASE_01C_PLAN §4.6). Uses the native
 * modal `<dialog>`: it traps focus, closes with Escape and returns focus to the opener.
 * Focus starts on "Cancel" so an accidental Enter does nothing harmful.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
      cancel.current?.focus();
    } else if (!open && element.open) {
      if (typeof element.close === "function") element.close();
      else element.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        // Escape: let React state decide, so the dialog and the state never disagree.
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <h2 id={titleId} className={styles.dialogTitle}>
        {title}
      </h2>
      <div>{children}</div>
      <div className={styles.actions}>
        <Button variant="danger" busy={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
        <Button ref={cancel} variant="secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </dialog>
  );
}
