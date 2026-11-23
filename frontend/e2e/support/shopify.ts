import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Connects a simulated Shopify store to an organization (task 2A-11). The backend helper runs
 * the real connect → link → import path with the in-process Shopify simulator, so nothing
 * reaches Shopify. The person must exist and manage the organization. Returns the store id.
 */
export function connectSimulatedStore(email: string, orgUrl: string, shop: string): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const output = execFileSync(
    "uv",
    ["run", "--frozen", "python", "-m", "tests.e2e_shopify_store"].concat([
      "--email",
      email,
      "--organization",
      organization,
      "--shop",
      shop,
    ]),
    {
      cwd: backend,
      encoding: "utf8",
      env: { ...process.env, LOG_LEVEL: "WARNING" },
      stdio: ["ignore", "pipe", "inherit"],
      timeout: 120_000,
    },
  );
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as { store_id?: string };
  if (!result.store_id) throw new Error("the simulated store was not connected");
  return result.store_id;
}
