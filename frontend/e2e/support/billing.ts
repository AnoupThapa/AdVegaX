import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Subscribes the organization through the Stripe simulator (task 13-08). The backend helper
 * turns billing on for itself only, starts Checkout as the owner, lets the simulator pay and
 * sends its signed event through the real webhook intake. Nothing reaches Stripe; the web
 * server has billing on but no Stripe key.
 */
export function subscribeWithSimulator(email: string, orgUrl: string, plan = "starter"): void {
  const organization = new URL(orgUrl).pathname.split("/")[2] ?? "";
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const args = ["run", "--frozen", "python", "-m", "tests.e2e_billing"];
  args.push("--email", email, "--organization", organization, "--plan", plan);
  const output = execFileSync("uv", args, {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING", THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: "50" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as { status?: string };
  if (result.status !== "active") throw new Error("the subscription was not applied");
}
