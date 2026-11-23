import { createOrganization, registeredUser } from "./support/actions";
import { subscribeWithSimulator } from "./support/billing";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";

/**
 * Phase 13 in the browser (task 13-08). A new organization is on the Growth trial; the Billing
 * page shows it, the usage and the plans. Choosing a plan on this test server (billing on, no
 * Stripe key) is refused plainly — nothing ever calls Stripe. After the Stripe simulator
 * subscribed the organization to Starter, the page shows the plan and Stripe's portal, and the
 * Members page explains the Starter member limit. Every page passes the accessibility check.
 */
test("billing shows the trial, the plan after Checkout and the limits", async ({ newPerson }) => {
  test.setTimeout(180_000);
  const person = await newPerson("owner");
  const page = person.page;
  person.expectFailedRequests(503); // choosing a plan without a Stripe key (on purpose)
  person.expectFailedRequests(403); // the member limit (on purpose)
  const email = uniqueEmail("bill");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Billing Co");

  await test.step("the trial, usage and plans", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Billing" }).click();
    await expect(page.getByText(/Free trial of the Growth plan until/)).toBeVisible();
    await expect(page.getByRole("table", { name: "Usage" })).toBeVisible();
    const plans = page.getByRole("list", { name: "Plans" });
    await expect(plans.getByRole("button", { name: "Choose Starter" })).toBeVisible();
    await expectAccessible(page, "billing on the trial");
    await plans.getByRole("button", { name: "Choose Starter" }).click();
    await expect(
      page.getByText("Billing is not available right now. Try again later."),
    ).toBeVisible();
  });

  await test.step("the plan after Checkout", async () => {
    subscribeWithSimulator(email, orgUrl, "starter");
    await page.reload();
    await expect(page.getByText(/Starter plan, monthly\. It renews on/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Manage billing in Stripe" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Plans" })).toHaveCount(0);
    await expectAccessible(page, "billing on Starter");
  });

  await test.step("the member limit is explained", async () => {
    await page.goto(`${orgUrl}/members`);
    const form = page.getByRole("form", { name: "Invite a member" });
    for (const n of [1, 2, 3]) {
      const invitee = uniqueEmail(`bill-m${n}`);
      await form.getByLabel("Email address").fill(invitee);
      await form.getByLabel("Role", { exact: true }).selectOption("viewer");
      await form.getByRole("button", { name: "Send invitation" }).click();
      if (n < 3) {
        await expect(
          page.getByText(`Invitation sent to ${invitee}.`, { exact: false }),
        ).toBeVisible();
      }
    }
    await expect(
      page.getByText("Your plan does not allow this. Change your plan on the Billing page."),
    ).toBeVisible();
    await expectAccessible(page, "member limit reached");
  });
});
