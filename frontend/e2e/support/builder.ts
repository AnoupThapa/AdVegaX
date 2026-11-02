import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Builds a simulated Google Ads campaign (task 10B-07). The backend helper switches the Action
 * Engine on for itself only and uses the real API with the in-process Google Ads simulator: it
 * approves the Google Ads creative, allows changes, builds a draft from the ready strategy,
 * launches it (checked, tested by the platform, approved, created paused, read back) and asks
 * for Go live, which waits for approval. Nothing reaches Google; the web server's engine stays
 * off.
 */
export function buildSimulatedCampaign(
  email: string,
  orgUrl: string,
  connectionId: string,
  strategyId: string,
  setId: string,
): { draft: string; launch: string; goLive: string; reference: string } {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_builder"];
  args.push("--email", email, "--organization", organization, "--connection", connectionId);
  args.push("--strategy", strategyId, "--set", setId);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    // Several helpers sign in as the same person within a minute: allow it in this helper only.
    env: { ...process.env, LOG_LEVEL: "WARNING", THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: "50" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as {
    draft?: string;
    launch?: string;
    go_live?: string;
    reference?: string;
  };
  if (!result.draft || !result.launch || !result.go_live || !result.reference) {
    throw new Error("no campaign was built");
  }
  return {
    draft: result.draft,
    launch: result.launch,
    goLive: result.go_live,
    reference: result.reference,
  };
}
