import { describe, expect, it } from "vitest";

import { safeNextPath } from "@/lib/navigation/safe-next";

describe("safeNextPath", () => {
  it.each([
    ["/orgs/123/members", "/orgs/123/members"],
    ["/account/security?tab=sessions#x", "/account/security?tab=sessions#x"],
    ["/a/../b", "/b"],
  ])("keeps same-origin paths (%s)", (raw, expected) => {
    expect(safeNextPath(raw)).toBe(expected);
  });

  it.each([
    null,
    undefined,
    "",
    "orgs/1",
    "//evil.example/x",
    "/\\evil.example",
    "https://evil.example/",
    "javascript:alert(1)",
    "/\tjavascript:alert(1)",
    "/path with space",
    "/x\u0000y",
    "/" + "a".repeat(600),
  ])("rejects %j", (raw) => {
    expect(safeNextPath(raw as string | null | undefined, "/home")).toBe("/home");
  });
});
