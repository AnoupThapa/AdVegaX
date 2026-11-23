/** The app-wide API client. Use `api` with `unwrap` in hooks and features. */

import { publicConfig } from "@/lib/config/public-config";

import { createApiClient } from "./client";

let unauthenticatedHandler: (() => void) | null = null;

/** Registered once by the app shell (clears cached data; later also redirects to sign-in). */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  unauthenticatedHandler = handler;
}

/** Called by the client on every 401. */
export function notifyUnauthenticated(): void {
  unauthenticatedHandler?.();
}

export const api = createApiClient({
  apiOrigin: publicConfig().apiOrigin,
  onUnauthenticated: notifyUnauthenticated,
});

export { unwrap } from "./client";
export { ApiError, friendlyMessage } from "./errors";
