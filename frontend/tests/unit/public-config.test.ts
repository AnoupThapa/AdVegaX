import { describe, expect, it } from "vitest";

import {
  assertPublicConfig,
  parsePublicConfig,
  PublicConfigError,
  publicConfig,
} from "@/lib/config/public-config";

describe("parsePublicConfig", () => {
  it("defaults to the local API", () => {
    expect(parsePublicConfig({})).toEqual({ apiOrigin: "http://localhost:8000" });
    expect(parsePublicConfig({ NEXT_PUBLIC_API_BASE_URL: "  " })).toEqual({
      apiOrigin: "http://localhost:8000",
    });
  });

  it("normalizes an https origin", () => {
    expect(parsePublicConfig({ NEXT_PUBLIC_API_BASE_URL: "https://api.example.com/" })).toEqual({
      apiOrigin: "https://api.example.com",
    });
  });

  it.each(["http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"])(
    "allows plain http only for local hosts (%s)",
    (url) => {
      expect(parsePublicConfig({ NEXT_PUBLIC_API_BASE_URL: url }).apiOrigin).toBe(url);
    },
  );

  it.each([
    ["not a url", "absolute URL"],
    ["ftp://api.example.com", "must use https"],
    ["javascript:alert(1)", "must use https"],
    ["http://api.example.com", "outside local development"],
    ["https://user:pass@api.example.com", "credentials"],
    ["https://api.example.com/api/v1", "origin only"],
    ["https://api.example.com/?x=1", "origin only"],
    ["https://api.example.com/#x", "origin only"],
  ])("rejects %s", (url, message) => {
    expect(() => parsePublicConfig({ NEXT_PUBLIC_API_BASE_URL: url })).toThrow(PublicConfigError);
    expect(() => assertPublicConfig({ NEXT_PUBLIC_API_BASE_URL: url })).toThrow(message);
  });

  it("reads the build-time environment", () => {
    const previous = process.env.NEXT_PUBLIC_API_BASE_URL;
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.org";
    try {
      expect(publicConfig().apiOrigin).toBe("https://api.example.org");
    } finally {
      process.env.NEXT_PUBLIC_API_BASE_URL = previous;
    }
  });
});
