import { readFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import openapiTS, { COMMENT_HEADER, astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "../..");

describe("generated API types (PHASE_01C_PLAN §2)", () => {
  it("schema.d.ts matches the committed OpenAPI schema", async () => {
    const schemaFile = path.join(ROOT, "lib/api/openapi.json");
    const ast = await openapiTS(pathToFileURL(schemaFile));
    const expected = COMMENT_HEADER + astToString(ast);
    const committed = readFileSync(path.join(ROOT, "lib/api/schema.d.ts"), "utf8");
    expect(committed === expected, "run `npm run api:generate` in frontend/").toBe(true);
  }, 30_000);
});
