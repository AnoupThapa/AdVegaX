import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Makes simulated recommendations (task 11-08). The backend helper writes 35 days of figures
 * for the simulated Google Ads campaigns, runs the daily look (AdVegaX's own rules) and, with
 * the Action Engine on for itself only and the Google Ads simulator, approves the pause it
 * proposes. The other advice stays open. Nothing reaches Google.
 */
export function createSimulatedRecommendations(
  email: string,
  orgUrl: string,
  connectionId: string,
): { approved: string; open: string; action: string } {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_recommendations"];
  args.push("--email", email, "--organization", organization, "--connection", connectionId);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    // Several helpers sign in as the same person within a minute: allow it in this helper only.
    env: { ...process.env, LOG_LEVEL: "WARNING", THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: "50" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as {
    approved?: string;
    open?: string;
    action?: string;
  };
  if (!result.approved || !result.open || !result.action) throw new Error("no advice was made");
  return { approved: result.approved, open: result.open, action: result.action };
}
