import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end suite (PHASE_01C_PLAN §9). Runs against a real stack: built web app, API, worker,
 * PostgreSQL, Redis and Mailpit. Start the stack first (README, "End-to-end and accessibility
 * tests"); nothing here starts servers. Tests share one backend, so they run one at a time.
 */
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_WEB_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
});
