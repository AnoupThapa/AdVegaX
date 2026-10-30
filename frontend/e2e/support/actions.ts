import type { BrowserContext, Page } from "@playwright/test";

import { PASSWORD } from "./env";
import { expect } from "./fixtures";
import { emailLink } from "./mail";

export async function signUp(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/sign-up");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL("/check-email");
}

export async function verifyEmail(page: Page, email: string): Promise<void> {
  await page.goto(await emailLink(email, "verify-email"));
  await expect(page.getByText("Your email address is verified.")).toBeVisible();
  await expect(page, "verification token removed from the address").not.toHaveURL(/token/);
}

/** Fills and submits the sign-in form on the current page. */
export async function submitSignIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function signIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/sign-in");
  await submitSignIn(page, email, password);
  await expect(page).toHaveURL("/");
  await expect(page.getByText("You are signed in as")).toBeVisible();
}

/** Signs up, verifies the email address and signs in. Ends on the home page. */
export async function registeredUser(page: Page, email: string): Promise<void> {
  await signUp(page, email);
  await verifyEmail(page, email);
  await signIn(page, email);
}

/** Creates an organization from the home page; returns its overview URL. */
export async function createOrganization(page: Page, name: string): Promise<string> {
  await page.goto("/orgs/new");
  await page.getByLabel("Organization name").fill(name);
  await page.getByLabel("Reporting currency").selectOption("AUD");
  await page.getByLabel("Time zone").selectOption("Australia/Sydney");
  await page.getByRole("button", { name: "Create organization" }).click();
  await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  return page.url();
}

/**
 * The local test platform's sign-in page does not exist (`fake-platform.invalid`). This answers
 * it the way an approving user would: back to the API callback with an approval code tied to the
 * PKCE challenge, as the fake provider expects.
 */
export async function approveTestPlatform(context: BrowserContext): Promise<void> {
  await context.route("https://fake-platform.invalid/**", async (route) => {
    const request = new URL(route.request().url());
    const back = new URL(request.searchParams.get("redirect_uri") ?? "");
    back.searchParams.set("state", request.searchParams.get("state") ?? "");
    back.searchParams.set("code", `approved.${request.searchParams.get("code_challenge") ?? ""}`);
    await route.fulfill({ status: 302, headers: { location: back.toString() } });
  });
}

/** Connects the test platform from the organization's Connections page; returns the detail URL. */
export async function connectTestPlatform(page: Page, orgUrl: string): Promise<string> {
  await approveTestPlatform(page.context());
  await page.goto(`${orgUrl}/connections`);
  await page.getByRole("button", { name: "Connect Test platform (local only)" }).click();
  await expect(page.getByText("Connected. We are now looking for the accounts")).toBeVisible();
  await page.getByRole("link", { name: /Test platform \(local only\) — Fake Business/ }).click();
  await expect(page).toHaveURL(/\/connections\/[0-9a-f-]{36}$/);
  return page.url();
}
