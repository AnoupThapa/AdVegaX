import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Makes a campaign strategy for the organization's first plannable product (task 8-07). The
 * backend helper asks the real API, with the in-process AI simulator as the planner's model, so
 * nothing reaches the AI provider. The person must exist and may plan strategies.
 */
export function createSimulatedStrategy(
  email: string,
  orgUrl: string,
): { strategyId: string; productTitle: string } {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_strategy"];
  args.push("--email", email, "--organization", organization);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as {
    strategy_id?: string;
    product_title?: string;
  };
  if (!result.strategy_id || !result.product_title) throw new Error("no strategy was made");
  return { strategyId: result.strategy_id, productTitle: result.product_title };
}
