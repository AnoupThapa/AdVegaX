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

export const navigation: { pathname: string; search: string; params: Record<string, string> } = {
  pathname: "/",
  search: "",
  params: {},
};

export function resetNavigation(): void {
  for (const fn of Object.values(router)) fn.mockReset();
  navigation.pathname = "/";
  navigation.search = "";
  navigation.params = {};
}

export const useRouter = () => router;
export const usePathname = () => navigation.pathname;
export const useSearchParams = () => new URLSearchParams(navigation.search);
export const useParams = () => navigation.params;
