import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Drafts the creatives of a strategy marked ready (task 9-07). The backend helper asks the real
 * API with the in-process AI simulator as the model, so nothing reaches the AI provider.
 */
export function createSimulatedCreatives(
  email: string,
  orgUrl: string,
  strategyId: string,
): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_creatives"];
  args.push("--email", email, "--organization", organization, "--strategy", strategyId);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    // Several helpers sign in as the same person within a minute: allow it in this helper only.
    env: { ...process.env, LOG_LEVEL: "WARNING", THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: "50" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as { set_id?: string };
  if (!result.set_id) throw new Error("no creatives were drafted");
  return result.set_id;
}
