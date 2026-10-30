import type { Locator, Page } from "@playwright/test";

import { signUp, verifyEmail } from "./support/actions";
import { PASSWORD, uniqueEmail } from "./support/env";
import { expect, test } from "./support/fixtures";

/**
 * Presses Tab (or Shift+Tab) until `target` has focus, failing if it is not reached within
 * `max` presses. Proves the control is reachable from the keyboard — focus is never set by script.
 */
async function tabTo(page: Page, target: Locator, { back = false, max = 25 } = {}): Promise<void> {
  for (let i = 0; i < max; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
  }
  await expect(target, `reachable with ${back ? "Shift+Tab" : "Tab"}`).toBeFocused({ timeout: 1 });
}

/** Keyboard-only use (PHASE_01C_PLAN §8): skip link, forms and dialogs without a mouse. */
test("the core flows work with the keyboard alone", async ({ newPerson }) => {
  const email = uniqueEmail("keyboard");
  const { page } = await newPerson("keyboard");
  await signUp(page, email);
  await verifyEmail(page, email);

  await test.step("focus starts on the page heading; the skip link is reachable and works", async () => {
    await page.goto("/sign-in");
    await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await tabTo(page, skip, { back: true, max: 8 });
    await expect(skip).toBeInViewport(); // visible when focused
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
  });

  await test.step("sign in using only Tab, typing and Enter", async () => {
    const emailField = page.getByLabel("Email", { exact: true });
    await tabTo(page, emailField);
    await page.keyboard.type(email);
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
    await page.keyboard.type(PASSWORD);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL("/");
  });

  await test.step("create an organization with the keyboard; the error moves focus", async () => {
    await page.goto("/orgs/new");
    const name = page.getByLabel("Organization name");
    const submit = page.getByRole("button", { name: "Create organization" });
    await tabTo(page, submit);
    await page.keyboard.press("Enter"); // submit empty
    await expect(name).toBeFocused(); // focus moves to the first error
    await page.keyboard.type("Keyboard Co");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Reporting currency")).toBeFocused();
    await page.keyboard.type("AUD"); // typing picks the matching option
    await expect(page.getByLabel("Reporting currency")).toHaveValue("AUD");
    await expect(page.getByLabel("Time zone")).not.toHaveValue(""); // defaults to this browser's zone
    await tabTo(page, submit);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Keyboard Co" })).toBeFocused();
  });

  await test.step("a confirmation dialog opens with Enter, closes with Escape, returns focus", async () => {
    await page.goto("/account/security");
    const everywhere = page.getByRole("button", { name: "Sign out everywhere" });
    await tabTo(page, everywhere, { max: 40 });
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(":focus")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(everywhere).toBeFocused();
  });
});
