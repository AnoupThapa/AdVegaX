import { registeredUser, signIn, submitSignIn } from "./support/actions";
import { PASSWORD, uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { emailLink } from "./support/mail";

const NEW_PASSWORD = "a brand new passphrase for e2e";

test("a forgotten password can be reset once from the emailed link", async ({ newPerson }) => {
  const email = uniqueEmail("reset");
  const person = await newPerson("reset");
  const { page } = person;
  await registeredUser(page, email);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL("/sign-in");

  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page).toHaveURL("/forgot-password");
  await expectAccessible(page, "forgot password");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("status").filter({ hasText: /\S/ })).toBeVisible();

  const link = await emailLink(email, "reset-password");
  await page.goto(link);
  await expect(page, "reset token removed from the address").not.toHaveURL(/token/);
  await expectAccessible(page, "reset password");
  await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await page.getByLabel("Confirm new password").fill(NEW_PASSWORD);
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(page.getByText("signed out on every device")).toBeVisible();

  await test.step("the same link cannot be used twice", async () => {
    person.expectFailedRequests(400);
    await page.goto("about:blank");
    await page.goto(link);
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
    await page.getByLabel("Confirm new password").fill(NEW_PASSWORD);
    await page.getByRole("button", { name: "Save new password" }).click();
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toBeVisible();
  });

  await test.step("the old password no longer works; the new one does", async () => {
    await page.goto("/sign-in");
    await submitSignIn(page, email, PASSWORD);
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toBeVisible();
    await signIn(page, email, NEW_PASSWORD);
  });
});
