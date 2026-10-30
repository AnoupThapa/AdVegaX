import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Connects a simulated WooCommerce store to an organization (task 2B-09). The backend helper
 * runs the real connect → key delivery → link → paged import path with the in-process
 * WooCommerce simulator, so nothing reaches a real store. The person must exist and manage the
 * organization. Returns the store id.
 */
export function connectSimulatedWooStore(
  email: string,
  orgUrl: string,
  host: string,
  options: { cogsOff?: boolean } = {},
): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_woocommerce_store"];
  args.push("--email", email, "--organization", organization, "--host", host);
  if (options.cogsOff) args.push("--cogs-off");
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as { store_id?: string };
  if (!result.store_id) throw new Error("the simulated WooCommerce store was not connected");
  return result.store_id;
}
