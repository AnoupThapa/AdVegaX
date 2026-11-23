import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Stores recorded ECB and Nepal Rastra Bank rates for the last 60 days (task 6-09). The backend
 * helper runs the real daily rate task against recorded-format answers, so nothing reaches
 * either bank. Safe to run more than once.
 */
export function loadRecordedRates(): number {
  const backend = process.env.E2E_BACKEND_DIR ?? path.resolve(process.cwd(), "..", "backend");
  const output = execFileSync("uv", ["run", "--frozen", "python", "-m", "tests.e2e_fx_rates"], {
    cwd: backend,
    encoding: "utf8",
    env: { ...process.env, LOG_LEVEL: "WARNING" },
    stdio: ["ignore", "pipe", "inherit"],
    timeout: 120_000,
  });
  const result = JSON.parse(output.trim().split("\n").pop() ?? "{}") as { rows?: number };
  if (result.rows === undefined) throw new Error("the recorded rates were not stored");
  return result.rows;
}
