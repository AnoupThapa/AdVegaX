/**
 * Client-side checks for quick feedback only. The API is authoritative (ARCHITECTURE §4):
 * it re-validates everything, and its password-policy messages are shown when they differ.
 */

/** Mirrors the API defaults (A15): PASSWORD_MIN_LENGTH / PASSWORD_MAX_LENGTH. */
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 128;

export type FieldErrors = Partial<Record<string, string[]>>;

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function emailErrors(email: string): string[] {
  const value = email.trim();
  if (!value) return ["Enter your email address."];
  if (value.length > 254 || !EMAIL_SHAPE.test(value)) return ["Enter a valid email address."];
  return [];
}

export function newPasswordErrors(password: string, email = ""): string[] {
  if (!password) return ["Enter a password."];
  const errors: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) {
    errors.push(`Use at least ${PASSWORD_MIN_LENGTH} characters.`);
  }
  if (password.length > PASSWORD_MAX_LENGTH) {
    errors.push(`Use at most ${PASSWORD_MAX_LENGTH} characters.`);
  }
  if (email && password.trim().toLowerCase() === email.trim().toLowerCase()) {
    errors.push("Your password must not be your email address.");
  }
  return errors;
}

export function hasErrors(errors: FieldErrors): boolean {
  return Object.values(errors).some((list) => (list?.length ?? 0) > 0);
}
