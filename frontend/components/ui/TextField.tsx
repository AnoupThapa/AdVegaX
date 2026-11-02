"use client";

import { forwardRef, useId, type InputHTMLAttributes } from "react";

import styles from "./ui.module.css";

type TextFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  readonly label: string;
  readonly hint?: string;
  /** Error messages for this field; linked to the input for screen readers. */
  readonly errors?: readonly string[];
};

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, errors = [], ...input },
  ref,
) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = errors.length ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {input.required ? null : <span className={styles.optional}> (optional)</span>}
      </label>
      {hint ? (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      <input
        {...input}
        ref={ref}
        id={id}
        className={styles.input}
        aria-invalid={errors.length ? true : undefined}
        aria-describedby={describedBy}
      />
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
