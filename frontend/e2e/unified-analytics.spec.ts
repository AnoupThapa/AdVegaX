import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAds } from "./support/google_ads";
import { connectSimulatedGoogleAnalytics } from "./support/google_analytics";
import { connectSimulatedMeta } from "./support/meta_ads";
import { connectSimulatedStore } from "./support/shopify";

/**
 * Phase 6 in the browser (task 6-09): one organization with a Shopify store, Google Ads (an
 * AUD and an NZD account), Meta and Google Analytics, all through their simulators, and
 * recorded exchange rates. The Overview shows sales, ad spend and profit together in AUD —
 * never 0 for what is missing — with where the numbers come from, the NZD conversion and the
 * time-zone note; Reports show each platform's own figures, the campaigns with their Google
 * Analytics match, and the products. Every page passes the accessibility check, and no
 * platform token ever reaches a page.
 */
test("sales, ad spend and profit are shown together, honestly", async ({ newPerson }) => {
  test.setTimeout(240_000);
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("unified");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Unified Co");
  loadRecordedRates();
  connectSimulatedStore(email, orgUrl, `e2e-${Date.now().toString(36)}`);
  connectSimulatedGoogleAds(email, orgUrl);
  connectSimulatedMeta(email, orgUrl);
  connectSimulatedGoogleAnalytics(email, orgUrl);
  const pages: string[] = [];

  await test.step("the Overview puts the figures together in the reporting currency", async () => {
    await page.goto(orgUrl);
    const tile = (group: string, label: string) =>
      page
        .getByRole("list", { name: group })
        .getByRole("listitem")
        .filter({ has: page.getByText(label, { exact: true }) });
    await expect(tile("Sales and profit", "Net sales")).toContainText(/\$29\.91/);
    await expect(tile("Sales and profit", "Gross profit")).toContainText(
      "Some products have no cost",
    );
    await expect(tile("Advertising", "Ad spend")).toContainText(/\$\d/);
    await expect(tile("Advertising", "Profit after ad spend")).toContainText(
      "Some products have no cost",
    );
    await expect(tile("Not included yet", "Shipping cost")).toContainText(
      "Not provided by the platform",
    );
    await expect(tile("Visits (Google Analytics)", "Sessions")).toContainText("160");
    await tile("Advertising", "Blended ROAS").getByText("How is this calculated?").click();
    await expect(page.getByText(/^Net sales \/ ad spend/)).toBeVisible();
    await expect(page.getByText("Eve Zone NZ")).toBeVisible();
    await expect(
      page.getByText(/Amounts in NZD are converted to AUD with European Central Bank rates/),
    ).toBeVisible();
    await expect(page.getByText(/different time zone from your reporting time zone/)).toBeVisible();
    await expectAccessible(page, "overview with figures");
    pages.push(await page.content());
  });

  await test.step("Reports show each platform's own figures and Google's channels", async () => {
    await page.getByRole("link", { name: "Reports", exact: true }).click();
    const platforms = page.getByRole("table", { name: /Reported by each platform/ });
    await expect(platforms.getByRole("row", { name: /Google Ads/ })).toContainText(
      "2 ad accounts · platform reported",
    );
    await expect(platforms.getByRole("row", { name: /Meta/ })).toBeVisible();
    const channels = page.getByRole("table", { name: /default channel groups/ });
    await expect(channels.getByRole("row", { name: /Paid Search/ })).toContainText("$120.50");
    await expectAccessible(page, "reports: channels");
    pages.push(await page.content());
  });

  await test.step("campaigns carry their Google Analytics match", async () => {
    await page.getByLabel("Report", { exact: true }).selectOption("campaigns");
    const campaigns = page.getByRole("table", { name: /campaign of the same name/ });
    await expect(
      campaigns.getByRole("row", { name: /Gloves - Search Google Ads · Eve Zone NZ/ }),
    ).toContainText("No matching Google Analytics campaign");
    await expectAccessible(page, "reports: campaigns");
    pages.push(await page.content());
  });

  await test.step("products show units, sales and missing costs", async () => {
    await page.getByLabel("Report", { exact: true }).selectOption("products");
    const products = page.getByRole("table", { name: /From your store platform/ });
    await expect(products.getByRole("row", { name: /Nitrile Gloves/ })).toBeVisible();
    await expectAccessible(page, "reports: products");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "platform tokens never reach a page").not.toMatch(
      /ya29\.|1\/\/sim-refresh|shp(at|rt)_|EAAsim|appsecret_proof/,
    );
  }
});
