"use client";

/**
 * The invitation token from the email link, kept **in memory only** (PHASE_01C_PLAN §4.3, §7).
 *
 * The accept page removes the token from the address bar at once. A signed-out invitee then
 * goes to sign in and comes back within the same tab (client-side navigation), so the token is
 * held here in the meantime. A reload or a new tab forgets it; the person simply opens the
 * email link again. Nothing is written to browser storage, cookies or URLs.
 */
let pendingToken: string | null = null;

export function rememberInvitationToken(token: string): void {
  pendingToken = token;
}

export function pendingInvitationToken(): string | null {
  return pendingToken;
}

export function forgetInvitationToken(): void {
  pendingToken = null;
}
