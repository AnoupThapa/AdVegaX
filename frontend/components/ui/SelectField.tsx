"use client";

import { forwardRef, useId, type SelectHTMLAttributes } from "react";

import styles from "./ui.module.css";

type SelectFieldProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, "id" | "children"> & {
  readonly label: string;
  readonly options: ReadonlyArray<{ readonly value: string; readonly label: string }>;
  /** Shown first with an empty value, e.g. "Choose a currency". */
  readonly placeholder?: string;
  readonly hint?: string;
  readonly errors?: readonly string[];
  /** Visually hide the label (it is still read by screen readers). */
  readonly hideLabel?: boolean;
};

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, options, placeholder, hint, errors = [], hideLabel = false, className, ...select },
  ref,
) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = errors.length ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={[styles.field, className].filter(Boolean).join(" ")}>
      <label htmlFor={id} className={hideLabel ? "visually-hidden" : styles.label}>
        {label}
      </label>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      <select
        {...select}
        ref={ref}
        id={id}
        className={styles.input}
        aria-invalid={errors.length ? true : undefined}
        aria-describedby={describedBy}
      >
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {errors.length ? (
        <ul id={errorId} className={styles.fieldErrors}>
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
});
