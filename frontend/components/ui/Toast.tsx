"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { Icon, type IconName } from "./Icon";
import styles from "./toast.module.css";

export type ToastTone = "success" | "info" | "warning" | "danger";

export type ToastInput = {
  readonly message: string;
  /** A few words in bold above the message. Optional. */
  readonly title?: string;
  readonly tone?: ToastTone;
  /** Milliseconds before it goes away on its own; `null` keeps it until dismissed. */
  readonly durationMs?: number | null;
};

type ToastItem = {
  readonly id: number;
  readonly message: string;
  readonly title: string | undefined;
  readonly tone: ToastTone;
  readonly durationMs: number | null;
};

type ToastApi = {
  /** Shows a notification and returns its id. */
  readonly show: (toast: ToastInput) => number;
  readonly dismiss: (id: number) => void;
};

/** Problems stay until dismissed, because they usually need action; the rest fade out. */
const DEFAULT_DURATION: Record<ToastTone, number | null> = {
  success: 5000,
  info: 6000,
  warning: 8000,
  danger: null,
};

const MAX_VISIBLE = 3;

/** `document.body` never changes, so there is nothing to subscribe to. */
const subscribeNever = () => () => {};

const ICON: Record<ToastTone, IconName> = {
  success: "check",
  info: "info",
  warning: "alert",
  danger: "alert",
};

const TONE_CLASS: Record<ToastTone, string> = {
  success: styles.success ?? "",
  info: styles.info ?? "",
  warning: styles.warning ?? "",
  danger: styles.danger ?? "",
};

const ToastContext = createContext<ToastApi | null>(null);

/** Shows short messages about something that just happened ("Settings saved"). */
export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside ToastProvider");
  return api;
}

function ToastView({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  const [paused, setPaused] = useState(false);

  // The timer stops while the pointer or keyboard focus is on the toast, so it can be read.
  useEffect(() => {
    if (toast.durationMs === null || paused) return;
    const timer = setTimeout(() => onDismiss(toast.id), toast.durationMs);
    return () => clearTimeout(timer);
  }, [toast.id, toast.durationMs, paused, onDismiss]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") onDismiss(toast.id);
  }

  return (
    // role="alert" is announced at once; role="status" waits for a pause in speech.
    <div
      role={toast.tone === "danger" ? "alert" : "status"}
      className={`${styles.toast} ${TONE_CLASS[toast.tone]}`}
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      onKeyDown={onKeyDown}
    >
      <span className={styles.icon}>
        <Icon name={ICON[toast.tone]} size={20} />
      </span>
      <p className={styles.text}>
        {toast.title ? <strong className={styles.title}>{toast.title}</strong> : null}
        {toast.message}
      </p>
      <button
        type="button"
        className={styles.close}
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
      >
        <Icon name="close" size={18} />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly ToastItem[]>([]);
  // The region lives in <body>, not inside the page: it never changes a component's own output and
  // exists before the first message, so screen readers are already listening when one arrives.
  const host = useSyncExternalStore(
    subscribeNever,
    () => document.body,
    () => null,
  );
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback((input: ToastInput) => {
    const id = nextId.current++;
    const tone = input.tone ?? "info";
    const item: ToastItem = {
      id,
      message: input.message,
      title: input.title,
      tone,
      durationMs: input.durationMs === undefined ? DEFAULT_DURATION[tone] : input.durationMs,
    };
    // Newest last, at most MAX_VISIBLE: the oldest makes way rather than the screen filling up.
    setToasts((current) => [...current, item].slice(-MAX_VISIBLE));
    return id;
  }, []);

  const api = useMemo<ToastApi>(() => ({ show, dismiss }), [show, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {host
        ? createPortal(
            <div className={styles.region}>
              {toasts.map((toast) => (
                <ToastView key={toast.id} toast={toast} onDismiss={dismiss} />
              ))}
            </div>,
            host,
          )
        : null}
    </ToastContext.Provider>
  );
}
