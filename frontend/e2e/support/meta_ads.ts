import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Connects a simulated Meta ad account to an organization (task 4-08). The backend helper runs
 * the real Facebook Login for Business → discovery by business → link → first import path with
 * the in-process Meta simulator, so nothing reaches Meta. The sign-in is made to end in 10 days
 * so its notice shows. The person must exist and manage the organization. Returns the ad
 * account's id.
 */
export function connectSimulatedMeta(email: string, orgUrl: string): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_meta_ads"];
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
  if (!result.ad_account_id) throw new Error("the simulated Meta ad account was not linked");
  return result.ad_account_id;
}
