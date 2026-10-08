import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "../..");
const SOURCE_DIRS = ["app", "components", "lib", "features", "hooks"];
const SOURCE_FILES = ["proxy.ts", "next.config.ts"];

function walk(dir: string): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return [];
  }
  return entries.flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.(ts|tsx|js|mjs)$/.test(name) ? [full] : [];
  });
}

const files = [
  ...SOURCE_DIRS.flatMap((d) => walk(path.join(ROOT, d))),
  ...SOURCE_FILES.map((f) => path.join(ROOT, f)),
];

const FORBIDDEN: Array<[RegExp, string]> = [
  [/\blocalStorage\b/, "browser storage"],
  [/\bsessionStorage\b/, "browser storage"],
  [/\bindexedDB\b/, "browser storage"],
  [/dangerouslySetInnerHTML/, "raw HTML rendering"],
  [/document\.cookie/, "cookie access"],
  [/\beval\s*\(/, "eval"],
  [/new\s+Function\s*\(/, "Function constructor"],
];

describe("frontend source rules (PHASE_01C_PLAN §7)", () => {
  it("scans the application source", () => {
    expect(files.length).toBeGreaterThan(5);
  });

  it.each(FORBIDDEN)("never uses %s (%s)", (pattern) => {
    const offenders = files.filter((file) => pattern.test(readFileSync(file, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("only exposes NEXT_PUBLIC_API_BASE_URL to the browser", () => {
    const names = new Set<string>();
    for (const file of files) {
      for (const match of readFileSync(file, "utf8").matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)) {
        names.add(match[0]);
      }
    }
    expect([...names]).toEqual(["NEXT_PUBLIC_API_BASE_URL"]);
  });
});
