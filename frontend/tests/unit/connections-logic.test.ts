import { afterEach, describe, expect, it, vi } from "vitest";

import { connectError, connectionStatus } from "@/features/connections/labels";
import { AVAILABILITY_LABELS, formatMetric, formatSyncedAt } from "@/lib/format/availability";
import { goToExternal } from "@/lib/navigation/external";

describe("formatMetric — never shows missing data as 0 (A10)", () => {
  it.each([
    [{ value: null, availability: "available" as const }, "Not available"],
    [{ value: 0, availability: "unavailable" as const }, "Not available"],
    [{ value: 0, availability: "unsupported" as const }, "Not supported by this platform"],
    [{ value: 0, availability: "not_synchronized" as const }, "Not synced yet"],
    [{ value: "", availability: "available" as const }, "Not available"],
    [{ value: "abc", availability: "available" as const }, "Not available"],
  ])("%j → %s", (metric, label) => {
    expect(formatMetric(metric)).toBe(label);
  });

  it("formats real values, including a real zero", () => {
    expect(formatMetric({ value: 0, availability: "available" }, "en-AU")).toBe("0");
    expect(formatMetric({ value: 1234.5, availability: "available" }, "en-AU")).toBe("1,234.5");
    expect(
      formatMetric({ value: "19.9", availability: "available", currency: "AUD" }, "en-AU"),
    ).toBe("$19.90");
    expect(AVAILABILITY_LABELS.not_synchronized).toBe("Not synced yet");
  });

  it("formats sync times or says they never happened", () => {
    expect(formatSyncedAt(null)).toBe("Not synced yet");
    expect(formatSyncedAt("2026-10-12T09:30:00Z", "en-AU")).toMatch(/2026/);
  });
});

describe("goToExternal — only https platform pages", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([
    "http://platform.example/oauth",
    "javascript:alert(1)",
    "https://user:pass@platform.example/",
    "not a url",
    "data:text/html,hi",
  ])("refuses %s", (url) => {
    const navigate = vi.fn();
    expect(goToExternal(url, navigate)).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
  });

  it("allows an https platform page", () => {
    const navigate = vi.fn();
    expect(goToExternal("https://platform.example/oauth?state=a b", navigate)).toBe(true);
    expect(navigate).toHaveBeenCalledWith("https://platform.example/oauth?state=a%20b");
  });
});

describe("labels", () => {
  it("connection statuses and connect errors read plainly", () => {
    expect(connectionStatus("active")).toEqual({ label: "Connected", tone: "ok" });
    expect(connectionStatus("expired").label).toBe("Needs reconnecting");
    expect(connectionStatus("weird")).toEqual({ label: "weird", tone: "warn" });
    expect(connectError("session_mismatch")).toMatch(/different account/);
    expect(connectError("auth_expired")).toMatch(/reconnect/);
    expect(connectError("unheard_of")).toMatch(/Something went wrong/);
    expect(connectError(null)).toMatch(/Something went wrong/);
  });
});
