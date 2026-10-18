import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Connects simulated Google Ads accounts to an organization (task 3-10). The backend helper
 * runs the real Google sign-in → discovery (through managers) → link two accounts → first
 * import path with the in-process Google Ads simulator, so nothing reaches Google. The person
 * must exist and manage the organization. Returns the AU ad account's id.
 */
export function connectSimulatedGoogleAds(email: string, orgUrl: string): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_google_ads"];
  args.push("--email", email, "--organization", organization);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as {
    ad_account_id?: string;
  };
  if (!result.ad_account_id) throw new Error("the simulated Google Ads accounts were not linked");
  return result.ad_account_id;
}
