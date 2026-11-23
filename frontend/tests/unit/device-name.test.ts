import { describe, expect, it } from "vitest";

import { deviceName } from "@/features/account/device-name";

describe("deviceName", () => {
  it.each([
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "Chrome on macOS",
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0",
      "Edge on Windows",
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
      "Firefox on Windows",
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
      "Safari on iPhone",
    ],
    [
      "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/140.0 Mobile/15E148 Safari/604.1",
      "Chrome on iPad",
    ],
    [
      "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36",
      "Chrome on Android",
    ],
    [
      "Mozilla/5.0 (Linux; Android 15; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/27.0 Chrome/125.0 Mobile Safari/537.36",
      "Samsung Internet on Android",
    ],
    [
      "Mozilla/5.0 (X11; CrOS x86_64 15000.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "Chrome on ChromeOS",
    ],
    [
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 OPR/120.0",
      "Opera on Linux",
    ],
  ])("%s", (ua, expected) => {
    expect(deviceName(ua)).toBe(expected);
  });

  it("handles missing and unrecognised values", () => {
    expect(deviceName(null)).toBe("Unknown device");
    expect(deviceName("   ")).toBe("Unknown device");
    expect(deviceName("Mozilla/5.0 (Windows NT 10.0)")).toBe("Windows");
    expect(deviceName("curl/8.5.0")).toBe("curl/8.5.0");
    expect(deviceName("x".repeat(60))).toBe(`${"x".repeat(40)}…`);
  });
});
