import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The design system's rules, enforced (docs/DESIGN_SYSTEM.md). Stylesheets may only use the
 * tokens defined in app/globals.css, so the look cannot drift one page at a time.
 */
const ROOT = path.resolve(__dirname, "../..");
const GLOBALS = path.join(ROOT, "app", "globals.css");
const SOURCE_DIRS = ["app", "components", "features"];

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return name.endsWith(".css") ? [full] : [];
  });
}

const sheets = SOURCE_DIRS.flatMap((d) => walk(path.join(ROOT, d)));
const modules = sheets.filter((file) => file !== GLOBALS);

type Declaration = { file: string; line: number; property: string; value: string };

function declarations(file: string): Declaration[] {
  const text = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, (c) =>
    c.replace(/[^\n]/g, " "),
  );
  const found: Declaration[] = [];
  text.split("\n").forEach((line, index) => {
    const match = /^\s*([a-z-]+)\s*:\s*([^;{}]+?)\s*(?:;|$)/.exec(line);
    // Custom properties (--x: …) define tokens; they are checked where they are defined.
    if (match && !match[1]!.startsWith("--")) {
      found.push({
        file: path.relative(ROOT, file),
        line: index + 1,
        property: match[1]!,
        value: match[2]!,
      });
    }
  });
  return found;
}

const all = modules.flatMap(declarations);

function violations(test: (d: Declaration) => boolean): string[] {
  return all.filter(test).map((d) => `${d.file}:${d.line}  ${d.property}: ${d.value}`);
}

/** Splits a value into its parts, keeping var(...) and calc(...) groups whole. */
function parts(value: string): string[] {
  return value.match(/(?:calc|var|min|max|clamp)\((?:[^()]|\([^()]*\))*\)|\S+/g) ?? [];
}

describe("design token rules", () => {
  it("finds the stylesheets it is meant to check", () => {
    expect(modules.length).toBeGreaterThan(15);
    expect(all.length).toBeGreaterThan(500);
  });

  it("uses no colour literals: only the palette tokens", () => {
    const COLOUR = /#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\(/i;
    expect(violations((d) => COLOUR.test(d.value) && !/var\(--/.test(d.value))).toEqual([]);
    expect(
      violations(
        (d) =>
          /\b(?:white|black|red|green|blue|gray|grey|orange|yellow)\b/.test(d.value) &&
          /color|background|border|shadow|fill|stroke/.test(d.property),
      ),
    ).toEqual([]);
  });

  it("sets font sizes only from the type scale", () => {
    expect(
      violations(
        (d) =>
          d.property === "font-size" && !/^(?:var\(--font-size-[a-z0-9]+\)|inherit)$/.test(d.value),
      ),
    ).toEqual([]);
  });

  it("sets font weights only from the weight tokens", () => {
    expect(
      violations(
        (d) =>
          d.property === "font-weight" &&
          !/^(?:var\(--font-weight-[a-z]+\)|inherit)$/.test(d.value),
      ),
    ).toEqual([]);
  });

  it("sets border radii only from the radius tokens", () => {
    expect(
      violations(
        (d) =>
          /^border(?:-[a-z]+)*-radius$/.test(d.property) &&
          !parts(d.value).every((p) => /^(?:var\(--radius-[a-z]+\)|0|50%|inherit)$/.test(p)),
      ),
    ).toEqual([]);
  });

  it("sets padding, margin and gaps only from the spacing tokens", () => {
    const SPACING = /^(?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)*$/;
    // A value built from tokens: var(--x), var(--x, var(--y)), calc(...) or max(...) containing a var(--…).
    const ALLOWED =
      /^(?:0|auto|inherit|-?[0-9.]+%|var\(--[a-z0-9-]+\)|(?:var|calc|max|min|clamp)\(.*var\(--.*\))$/;
    expect(
      violations((d) => SPACING.test(d.property) && !parts(d.value).every((p) => ALLOWED.test(p))),
    ).toEqual([]);
  });

  it("layers with the z-index tokens", () => {
    expect(
      violations(
        (d) => d.property === "z-index" && !/^(?:var\(--z-[a-z]+\)|-?[0-9]|auto)$/.test(d.value),
      ),
    ).toEqual([]);
  });

  it("does not use !important", () => {
    expect(violations((d) => /!important/.test(d.value))).toEqual([]);
  });
});
