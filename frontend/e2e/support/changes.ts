import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Makes a simulated change and its undo (task 10A-07). The backend helper switches the Action
 * Engine on for itself only and uses the real API with the in-process Google Ads simulator:
 * changes are allowed for the connection, a daily budget change is checked, approved, sent,
 * read back and verified, and its undo waits for approval. Nothing reaches Google; the web
 * server's own engine stays off.
 */
export function createSimulatedChanges(
  email: string,
  orgUrl: string,
  connectionId: string,
): { done: string; undo: string; campaign: string } {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_actions"];
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
    done?: string;
    undo?: string;
    campaign?: string;
  };
  if (!result.done || !result.undo || !result.campaign) throw new Error("no change was made");
  return { done: result.done, undo: result.undo, campaign: result.campaign };
}
