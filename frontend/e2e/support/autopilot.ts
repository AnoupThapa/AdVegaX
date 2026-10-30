import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Lets autopilot make a simulated change (task 12-07). The backend helper switches the Action
 * Engine and autopilot on for itself only, writes figures, has the owner approve one piece of
 * advice (the organization is then ready), switches autopilot on for the NZ account and lets
 * it pause that campaign through the Action Engine with the Google Ads simulator. Nothing
 * reaches Google; the web server's own engine and autopilot stay off.
 */
export function createAutopilotChange(
  email: string,
  orgUrl: string,
  connectionId: string,
): { action: string; recommendation: string } {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_autopilot"];
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
    action?: string;
    recommendation?: string;
  };
  if (!result.action || !result.recommendation) throw new Error("autopilot made no change");
  return { action: result.action, recommendation: result.recommendation };
}
