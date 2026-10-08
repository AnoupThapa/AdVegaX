/**
 * Shared Next.js navigation mock. In a test file:
 *   vi.mock("next/navigation", () => import("../support/navigation"));
 * then inspect `router` and set `navigation.search` / `navigation.pathname`.
 */
import { vi } from "vitest";

export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

export const navigation = { pathname: "/", search: "" };

export function resetNavigation(): void {
  for (const fn of Object.values(router)) fn.mockReset();
  navigation.pathname = "/";
  navigation.search = "";
}

export const useRouter = () => router;
export const usePathname = () => navigation.pathname;
export const useSearchParams = () => new URLSearchParams(navigation.search);
