import { registeredUser, signIn } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";

test("a person can sign out another device, then every device", async ({ newPerson }) => {
  const email = uniqueEmail("sessions");
  const laptop = (await newPerson("laptop")).page;
  const phone = (await newPerson("phone")).page;
  await registeredUser(laptop, email);
  await signIn(phone, email);

  await laptop.goto("/account/security");
  await expect(laptop.getByRole("heading", { name: "Account security" })).toBeVisible();
  const sessions = laptop.getByRole("table");
  await expect(sessions.getByRole("row")).toHaveCount(3); // header + two sessions
  await expect(sessions.getByText("This device")).toBeVisible();
  await expectAccessible(laptop, "account security");

  await test.step("the laptop signs the phone out", async () => {
    await sessions.getByRole("button", { name: /^Sign out of / }).click();
    const dialog = laptop.getByRole("dialog");
    await expectAccessible(laptop, "sign out device confirmation");
    await dialog.getByRole("button", { name: "Sign out device" }).click();
    await expect(sessions.getByRole("row")).toHaveCount(2);

    await phone.goto("/account/security");
    await expect(phone).toHaveURL(/\/sign-in\?next=%2Faccount%2Fsecurity$/);
  });

  await test.step("sign out everywhere ends the laptop's own session too", async () => {
    await laptop.getByRole("button", { name: "Sign out everywhere" }).click();
    await laptop.getByRole("dialog").getByRole("button", { name: "Sign out everywhere" }).click();
    await expect(laptop).toHaveURL(/\/sign-in\?next=%2Faccount%2Fsecurity$/);
  });
});
