import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { connectSimulatedGoogleAnalytics } from "./support/google_analytics";

/**
 * Phase 5 in the browser (task 5-09): Google Analytics is offered as read-only on the
 * Connections page; the properties found through the simulator are grouped under their
 * Analytics account (one without a currency says why it cannot be linked); the Analytics tab
 * lists the linked property; the property page shows Google's figures with users per day
 * only, the processing and privacy-threshold notes, and where visits came from. Every page
 * passes the accessibility check, and no Google token ever reaches a page.
 */
test("a GA4 property is imported and shown honestly", async ({ newPerson }) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("ga4");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Analytics Co");
  const propertyId = connectSimulatedGoogleAnalytics(email, orgUrl);
  const pages: string[] = [];

  await test.step("Connections offers Google Analytics as read-only", async () => {
    await page.goto(`${orgUrl}/connections`);
    await expect(page.getByRole("button", { name: "Connect Google Analytics" })).toBeVisible();
    await expect(page.getByText(/never changes anything in Google Analytics/)).toBeVisible();
    await expectAccessible(page, "connections with Google Analytics");
    pages.push(await page.content());
  });

  await test.step("the connection page groups properties by Analytics account", async () => {
    await page
      .getByRole("link", { name: /^Google Analytics/ })
      .first()
      .click();
    const eveZone = page.getByRole("table", { name: "Analytics account: Eve Zone" });
    await expect(eveZone).toBeVisible();
    await expect(eveZone.getByText("Eve Zone AU")).toBeVisible();
    const mediflex = page.getByRole("table", { name: "Analytics account: Mediflex" });
    await expect(mediflex.getByText(/did not give its currency or time zone/)).toBeVisible();
    await expectAccessible(page, "Google Analytics connection");
    pages.push(await page.content());
  });

  await test.step("the Analytics tab lists the property", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Analytics", exact: true }).click();
    await expect(page.getByRole("link", { name: "Eve Zone AU" })).toBeVisible();
    await expect(
      page.getByText("Google Analytics · Eve Zone · AUD · Australia/Sydney"),
    ).toBeVisible();
    await expect(page.getByText("Up to date")).toBeVisible();
    await expectAccessible(page, "analytics tab");
    pages.push(await page.content());
  });

  await test.step("the property page shows Google's figures honestly", async () => {
    await page.getByRole("link", { name: "Eve Zone AU" }).click();
    await expect(page).toHaveURL(`${orgUrl}/analytics/${propertyId}`);
    await expect(page.getByText(/Reported by Google Analytics/).first()).toBeVisible();
    const totals = page.getByRole("list", { name: "Totals for the period" });
    const tile = (label: string) =>
      totals.getByRole("listitem").filter({ has: page.getByText(label, { exact: true }) });
    await expect(tile("Sessions")).toContainText("160");
    await expect(tile("Users")).toContainText("Shown per day only");
    await expect(tile("Purchase revenue")).toContainText("$290.40"); // 189.90 + 120.50 - 20.00
    await expect(page.getByText(/still being processed by Google/).first()).toBeVisible();
    await expect(page.getByText(/withheld some small numbers/).first()).toBeVisible();
    const channels = page.getByRole("table", { name: /Channels with their own figures/ });
    await expect(channels.getByRole("row", { name: /Paid Search/ })).toContainText("$120.50");
    await page.getByLabel("Show").selectOption("source");
    const sources = page.getByRole("table", { name: /Sources, mediums and campaigns/ });
    await expect(sources.getByRole("row", { name: /google \/ cpc/ })).toContainText("Spring Sale");
    await expect(page.getByRole("button", { name: "Sync now" })).toBeVisible();
    await expectAccessible(page, "Google Analytics property");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "Google tokens never reach a page").not.toMatch(/ya29\.|1\/\/sim-refresh/);
  }
});
