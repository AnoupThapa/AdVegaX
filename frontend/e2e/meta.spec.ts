import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { connectSimulatedMeta } from "./support/meta_ads";

/**
 * Phase 4 in the browser (task 4-08): Meta is offered as read-only on the Connections page;
 * a Meta ad account found through the simulator is grouped under its business (one with an
 * unpaid balance says why it cannot be linked); the sign-in's end date and its notice show
 * from 14 days before; the Advertising tab lists the account with its platform and business;
 * the account page speaks Meta's words (purchases, link clicks, "Reported by Meta"); the
 * campaign page shows ad sets and ads. Every page passes the accessibility check, and no Meta
 * token ever reaches a page.
 */
test("a Meta ad account is imported and shown in Meta's words", async ({ newPerson }) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("meta");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Meta Co");
  const accountId = connectSimulatedMeta(email, orgUrl);
  const pages: string[] = [];

  await test.step("Connections offers Meta and shows when the sign-in ends", async () => {
    await page.goto(`${orgUrl}/connections`);
    await expect(page.getByRole("button", { name: "Connect Meta" })).toBeVisible();
    await expect(
      page.getByText(/Facebook account you use for Meta ads.*only reads them/),
    ).toBeVisible();
    await expect(page.getByText(/Sign-in ends/)).toBeVisible();
    await expect(page.getByText(/The Meta sign-in ends in 10 days/)).toBeVisible();
    await expectAccessible(page, "connections with Meta");
    pages.push(await page.content());
  });

  await test.step("the connection page groups ad accounts by business", async () => {
    await page.getByRole("link", { name: /^Meta/ }).first().click();
    const business = page.getByRole("table", { name: "Business: Eve Zone Business" });
    await expect(business).toBeVisible();
    await expect(page.getByRole("table", { name: "Not in a business: 1 account" })).toBeVisible();
    await expect(business.getByText("Has an unpaid balance in Meta")).toBeVisible();
    await expect(page.getByRole("link", { name: "Reconnect" })).toBeVisible();
    await expectAccessible(page, "Meta connection");
    pages.push(await page.content());
  });

  await test.step("the Advertising tab lists the account with its platform", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Advertising", exact: true }).click();
    await expect(page.getByRole("link", { name: "Eve Zone AU" })).toBeVisible();
    await expect(page.getByText("Meta · Eve Zone Business · AUD · Australia/Sydney")).toBeVisible();
    await expect(page.getByText("Up to date")).toBeVisible();
    await expectAccessible(page, "advertising with Meta");
    pages.push(await page.content());
  });

  await test.step("the account page shows Meta's figures in Meta's words", async () => {
    await page.getByRole("link", { name: "Eve Zone AU" }).click();
    await expect(page).toHaveURL(`${orgUrl}/advertising/${accountId}`);
    await expect(page.getByText(/Reported by Meta/).first()).toBeVisible();
    await expect(page.getByText(/The Meta sign-in ends in 10 days/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Reconnect Meta" })).toBeVisible();
    const totals = page.getByRole("list", { name: "Totals for the period" });
    await expect(totals.getByText("Purchases", { exact: true })).toBeVisible();
    await expect(totals.getByText("Link clicks")).toBeVisible();
    await expect(totals.getByText(/\$48\.75$/)).toBeVisible(); // spend, exact
    await expect(totals.getByText(/\$159\.90$/)).toBeVisible(); // purchase value
    const campaigns = page.getByRole("table", { name: /Campaigns with their own figures/ });
    await expect(campaigns.getByText("$50.00 a day")).toBeVisible(); // 5,000 cents
    await expect(campaigns.getByRole("row", { name: /Winter/ })).toContainText("Archived");
    await expect(campaigns.getByRole("row", { name: /Test/ })).toContainText("Removed");
    await expectAccessible(page, "Meta ad account");
    pages.push(await page.content());
  });

  await test.step("the campaign page shows ad sets and ads", async () => {
    await page.getByRole("link", { name: "Gloves - Sales" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Ad sets and ads" })).toBeVisible();
    const ads = page.getByRole("table", { name: "Ads in AU buyers" });
    await expect(ads.getByRole("columnheader", { name: "Purchases" })).toBeVisible();
    await expect(ads.getByText("Vinyl gloves video")).toBeVisible();
    await expectAccessible(page, "Meta campaign");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "Meta tokens never reach a page").not.toMatch(/EAAsim|appsecret_proof/);
  }
});
