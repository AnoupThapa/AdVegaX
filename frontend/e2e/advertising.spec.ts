import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { connectSimulatedGoogleAds } from "./support/google_ads";

/**
 * Phase 3 in the browser (task 3-10): Google Ads accounts found through the simulator are
 * grouped under their manager accounts on the connection page (a cancelled one says why it
 * cannot be linked); the Advertising tab lists the linked accounts; the account page shows
 * Google's figures with derived rates, "may still change" days and the campaign table; the
 * campaign page shows ad groups and ads. Every page is labelled "Reported by Google Ads",
 * passes the accessibility check, and no Google token ever reaches a page.
 */
test("Google Ads accounts are imported and shown with their figures", async ({ newPerson }) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("ads");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Ads Co");
  const accountId = connectSimulatedGoogleAds(email, orgUrl);
  const pages: string[] = [];

  await test.step("the connection page groups accounts under their managers", async () => {
    await page.goto(`${orgUrl}/connections`);
    await page
      .getByRole("link", { name: /^(Google Ads|google_ads)/ })
      .first()
      .click();
    const direct = page.getByRole("table", { name: /^Directly accessible/ });
    await expect(direct).toBeVisible();
    await expect(page.getByRole("table", { name: /^Through / })).toBeVisible();
    await expect(direct.getByText("Cannot be linked")).toBeVisible();
    await expect(direct.getByText("Cancelled, suspended or closed in Google Ads")).toBeVisible();
    await expectAccessible(page, "Google Ads connection");
    pages.push(await page.content());
  });

  await test.step("the Advertising tab lists the linked ad accounts", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Advertising", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Advertising" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Eve Zone AU" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Eve Zone NZ" })).toBeVisible();
    await expect(page.getByText("Up to date")).toHaveCount(2);
    await expectAccessible(page, "advertising (two accounts)");
    pages.push(await page.content());
  });

  await test.step("the account page shows Google's figures and campaigns", async () => {
    await page.getByRole("link", { name: "Eve Zone AU" }).click();
    await expect(page).toHaveURL(`${orgUrl}/advertising/${accountId}`);
    await expect(page.getByRole("heading", { level: 1, name: "Eve Zone AU" })).toBeVisible();
    await expect(page.getByText(/Reported by Google Ads/).first()).toBeVisible();
    const totals = page.getByRole("list", { name: "Totals for the period" });
    await expect(totals.getByText(/\$12\.35$/)).toBeVisible(); // spend, exact from micros
    await expect(totals.getByText(/2\.0%$/)).toBeVisible(); // 34 clicks ÷ 1,700 impressions
    await expect(page.getByText("may still change").first()).toBeVisible();
    const campaigns = page.getByRole("table", { name: /Campaigns with their own figures/ });
    await expect(campaigns.getByText("$50.00 a day (shared)")).toBeVisible();
    await expect(campaigns.getByRole("row", { name: /Old test/ })).toContainText("Removed");
    await expect(page.getByRole("button", { name: "Sync now" })).toBeEnabled();
    await expectAccessible(page, "ad account");
    pages.push(await page.content());
  });

  await test.step("the campaign page shows ad groups and ads", async () => {
    await page.getByRole("link", { name: "Gloves - Search" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Gloves - Search" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Ads in Nitrile gloves" })).toBeVisible();
    await expectAccessible(page, "campaign");
    pages.push(await page.content());
    await page.getByRole("link", { name: "← Ad account" }).click();
    await page.getByRole("link", { name: "Spring - PMax" }).click();
    await expect(page.getByText(/report figures only for the whole campaign/)).toBeVisible();
    await expectAccessible(page, "campaign without ad groups");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "Google tokens never reach a page").not.toMatch(/ya29\.|1\/\/sim-refresh/);
  }
});
