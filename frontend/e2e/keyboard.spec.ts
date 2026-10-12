import { signUp, verifyEmail } from "./support/actions";
import { PASSWORD, uniqueEmail } from "./support/env";
import { expect, test } from "./support/fixtures";

/** Keyboard-only use (PHASE_01C_PLAN §8): skip link, forms, menus and dialogs without a mouse. */
test("the core flows work with the keyboard alone", async ({ newPerson }) => {
  const email = uniqueEmail("keyboard");
  const { page } = await newPerson("keyboard");
  await signUp(page, email);
  await verifyEmail(page, email);

  await test.step("focus starts on the page heading; the skip link jumps to the content", async () => {
    await page.goto("/sign-in");
    await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await skip.focus();
    await expect(skip).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
  });

  await test.step("sign in using only Tab, typing and Enter", async () => {
    const emailField = page.getByLabel("Email", { exact: true });
    await page.getByRole("heading", { level: 1 }).focus();
    await page.keyboard.press("Tab");
    await expect(emailField).toBeFocused();
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
    await name.focus();
    await page.keyboard.press("Enter"); // submit empty
    await expect(name).toBeFocused();
    await page.keyboard.type("Keyboard Co");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Reporting currency")).toBeFocused();
    await page.keyboard.type("AUD"); // typing picks the matching option
    await expect(page.getByLabel("Reporting currency")).toHaveValue("AUD");
    await expect(page.getByLabel("Time zone")).not.toHaveValue(""); // defaults to this browser's zone
    await name.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/orgs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Keyboard Co" })).toBeFocused();
  });

  await test.step("a confirmation dialog closes with Escape and returns focus", async () => {
    await page.goto("/account/security");
    const everywhere = page.getByRole("button", { name: "Sign out everywhere" });
    await everywhere.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(":focus")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(everywhere).toBeFocused();
  });
});
