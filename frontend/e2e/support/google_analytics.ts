import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Connects a simulated GA4 property to an organization (task 5-09). The backend helper runs
 * the real Google sign-in → discovery by Analytics account → link → first import path with the
 * in-process GA4 simulator, so nothing reaches Google. The person must exist and manage the
 * organization. Returns the property's id.
 */
export function connectSimulatedGoogleAnalytics(email: string, orgUrl: string): string {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_google_analytics"];
  args.push("--email", email, "--organization", organization);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as {
    property_id?: string;
  };
  if (!result.property_id) throw new Error("the simulated GA4 property was not linked");
  return result.property_id;
}
