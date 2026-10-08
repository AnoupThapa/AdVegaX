import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { StrictMode, type ReactElement } from "react";

import { SESSION_KEY, type SessionUser } from "@/features/auth/session";

export function testUser(overrides: Partial<SessionUser> = {}): SessionUser {
  return {
    id: "user-1",
    email: "ada@example.com",
    display_name: "Ada",
    email_verified: true,
    memberships: [],
    ...overrides,
  } as SessionUser;
}

/** Renders with a fresh query cache (no retries). `session` pre-sets the signed-in user. */
export function renderWithProviders(
  ui: ReactElement,
  { session, strict = false }: { session?: SessionUser | null; strict?: boolean } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  if (session !== undefined) queryClient.setQueryData(SESSION_KEY, session);
  const tree = <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>;
  return { queryClient, ...render(strict ? <StrictMode>{tree}</StrictMode> : tree) };
}
