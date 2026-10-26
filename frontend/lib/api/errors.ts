/**
 * API error envelope (API_SPECIFICATION §2) and user-facing messages.
 * Raw server text is never shown: every code maps to our own wording (PHASE_01C_PLAN §7).
 */

export type ApiErrorDetail = {
  readonly location?: readonly string[];
  readonly message?: string;
  readonly type?: string;
  /** A plain code saying why, e.g. why a store could not be reached (2B). */
  readonly reason?: string;
};

export type ApiErrorBody = {
  readonly error: {
    readonly code: string;
    readonly message?: string;
    readonly details?: readonly ApiErrorDetail[];
  };
  readonly meta?: { readonly request_id?: string | null };
};

/** Client-side codes for failures that never reached or never came back from the API. */
export const NETWORK_ERROR = "NETWORK_ERROR";
export const UNEXPECTED_RESPONSE = "UNEXPECTED_RESPONSE";

export class ApiError extends Error {
  override readonly name = "ApiError";

  constructor(
    /** HTTP status; 0 when the request never completed. */
    readonly status: number,
    readonly code: string,
    readonly details: readonly ApiErrorDetail[] = [],
    /** Correlation ID to quote to support; never contains secrets. */
    readonly requestId: string | null = null,
  ) {
    super(code);
  }

  /** Validation messages for one form field, e.g. fieldErrors("email"). */
  fieldErrors(field: string): string[] {
    return this.details
      .filter((d) => d.location?.at(-1) === field && d.message)
      .map((d) => d.message as string);
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

/** Builds an ApiError from a failed response's status, parsed body and headers. */
export function apiErrorFrom(status: number, body: unknown, headers?: Headers): ApiError {
  const headerId = headers?.get("x-request-id") ?? null;
  if (isErrorBody(body)) {
    return new ApiError(
      status,
      body.error.code,
      body.error.details ?? [],
      body.meta?.request_id ?? headerId,
    );
  }
  const code = status >= 500 ? "INTERNAL_ERROR" : UNEXPECTED_RESPONSE;
  return new ApiError(status, code, [], headerId);
}

const MESSAGES: Readonly<Record<string, string>> = {
  VALIDATION_ERROR: "Some details are missing or invalid. Please check the form.",
  BAD_REQUEST: "This request could not be processed.",
  UNAUTHENTICATED: "Please sign in to continue.",
  INVALID_CREDENTIALS: "The email or password is incorrect.",
  FORBIDDEN: "You do not have permission to do this.",
  EMAIL_NOT_VERIFIED: "Please verify your email address first.",
  CSRF_FAILED: "Your session security check failed. Please reload the page and try again.",
  INVITATION_EMAIL_MISMATCH: "This invitation was sent to a different email address.",
  NOT_FOUND: "This page does not exist, or you do not have access to it.",
  METHOD_NOT_ALLOWED: "This action is not available.",
  CONFLICT: "This change conflicts with the current state. Please refresh and try again.",
  SLUG_TAKEN: "That address is already taken. Please choose another.",
  ALREADY_MEMBER: "This person is already a member of the organization.",
  LAST_OWNER: "An organization must keep at least one owner.",
  INVITATION_NOT_PENDING: "This invitation is no longer valid.",
  INVALID_TOKEN: "This link is invalid or has expired. Please request a new one.",
  PAYLOAD_TOO_LARGE: "The request is too large.",
  UNSUPPORTED_MEDIA_TYPE: "This request format is not supported.",
  RATE_LIMITED: "Too many attempts. Please wait a few minutes and try again.",
  AI_LIMIT_REACHED:
    "Today's AI planning limit for this organization is reached. Please try again tomorrow.",
  AI_UNAVAILABLE: "The AI planner is not available right now. Please try again later.",
  AI_ANSWER_REJECTED:
    "The AI's answer did not pass AdVegaX's checks, so nothing was saved. Please try again.",
  PRODUCT_NOT_PLANNABLE: "A strategy cannot be made for this product right now.",
  STRATEGY_ARCHIVED: "This strategy is archived and can no longer be changed.",
  INTERNAL_ERROR: "Something went wrong on our side. Please try again.",
  SERVICE_UNAVAILABLE: "The service is temporarily unavailable. Please try again shortly.",
  HTTP_ERROR: "This request could not be completed. Please try again.",
  UNKNOWN_PROVIDER: "This platform is not available.",
  ACCOUNT_IN_USE:
    "This account is already connected to another AdVegaX organization. Ask its owner to disconnect it first.",
  STORE_NOT_REACHABLE:
    "AdVegaX could not reach the store's WooCommerce API at this address. Check the address and that the store is online.",
  INVALID_KEY_DELIVERY:
    "The store's credentials could not be accepted. Please try connecting again.",
  INVALID_CONNECT_PARAMS:
    "Check the details you entered for this platform (for example the store address).",
  CONNECTION_NOT_ACTIVE: "This connection is not active. Reconnect the platform first.",
  RESOURCE_NOT_LINKABLE: "This account is no longer accessible through its connection.",
  RESOURCE_UNAVAILABLE:
    "This account cannot be linked. It may be a manager account or one that is cancelled or suspended on the platform.",
  ALREADY_LINKED: "This account is already linked to the organization.",
  NOT_LINKED: "This account is not linked to the organization.",
  SYNC_IN_PROGRESS: "This is already being updated. Please wait until it finishes.",
  STORE_NOT_SYNCING:
    "This store is not linked to an active connection. Link or reconnect it first.",
  AD_ACCOUNT_NOT_SYNCING:
    "This ad account is not linked to an active connection. Link or reconnect it first.",
  ANALYTICS_PROPERTY_NOT_SYNCING:
    "This Google Analytics property is not linked to an active connection. Link or reconnect it first.",
  // Platform-to-AdVegaX webhook answers; a person should never see these, but keep them friendly.
  INVALID_SIGNATURE: "The request could not be verified.",
  INVALID_WEBHOOK: "The request could not be processed.",
  [NETWORK_ERROR]: "We could not reach AdVegaX. Check your connection and try again.",
  [UNEXPECTED_RESPONSE]: "Something went wrong. Please try again.",
};

const FALLBACK = "Something went wrong. Please try again.";

/** The text to show a person for an error code. Unknown codes get a generic message. */
export function friendlyMessage(error: ApiError | string): string {
  const code = typeof error === "string" ? error : error.code;
  return MESSAGES[code] ?? FALLBACK;
}

/** The text to show for anything thrown by an API call (non-API errors get the generic text). */
export function messageFor(error: unknown): string {
  return error instanceof ApiError ? friendlyMessage(error) : friendlyMessage(UNEXPECTED_RESPONSE);
}

/** Every code with a dedicated message (used by tests to stay in sync with the API). */
export const KNOWN_ERROR_CODES: readonly string[] = Object.keys(MESSAGES);
