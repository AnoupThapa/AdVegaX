import { ApiError, friendlyMessage } from "@/lib/api/errors";

import type { FieldErrors } from "./validation";

/**
 * Turns an API error into form feedback. Password-policy messages are written for people and
 * are shown as-is; any other field problem gets our own generic wording (PHASE_01C_PLAN §7).
 */
export function formFeedback(
  error: unknown,
  fieldAliases: Readonly<Record<string, string>> = {},
): { fields: FieldErrors; message: string; requestId: string | null } {
  if (!(error instanceof ApiError)) {
    return { fields: {}, message: friendlyMessage("UNEXPECTED_RESPONSE"), requestId: null };
  }
  const fields: FieldErrors = {};
  if (error.code === "VALIDATION_ERROR") {
    for (const detail of error.details) {
      const raw = detail.location?.at(-1);
      if (!raw) continue;
      const field = fieldAliases[raw] ?? raw;
      const text =
        detail.type === "password_policy" && detail.message
          ? detail.message
          : "Check this field and try again.";
      const list = (fields[field] ??= []);
      if (!list.includes(text)) list.push(text);
    }
  }
  return { fields, message: friendlyMessage(error), requestId: error.requestId };
}
