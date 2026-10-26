import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAds } from "./support/google_ads";
import { connectSimulatedGoogleAnalytics } from "./support/google_analytics";
import { connectSimulatedMeta } from "./support/meta_ads";
import { connectSimulatedStore } from "./support/shopify";
import { createSimulatedStrategy } from "./support/strategy";

/**
 * Phase 6 in the browser (task 6-09): one organization with a Shopify store, Google Ads (an
 * AUD and an NZD account), Meta and Google Analytics, all through their simulators, and
 * recorded exchange rates. The Overview shows sales, ad spend and profit together in AUD —
 * never 0 for what is missing — with where the numbers come from, the NZD conversion and the
 * time-zone note; Reports show each platform's own figures, the campaigns with their Google
 * Analytics match, and the products. Phase 8 (8-07): a campaign strategy made with the AI
 * simulator shows its amounts and the figures behind it, is edited, marked ready and archived;
 * asking for a new one while this installation's planner is off says so plainly. Every page passes the accessibility check, and no
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

  await test.step("the funnel shows each stage with its source", async () => {
    await page.getByRole("link", { name: "Funnel", exact: true }).click();
    const stages = page.getByRole("list", { name: "Stages" });
    await expect(stages.getByRole("listitem").first()).toContainText("Google Ads and Meta");
    await expect(page.getByText(/Different sources — no rate/)).toBeVisible();
    await expectAccessible(page, "funnel");
    await page.getByLabel("Show", { exact: true }).selectOption("platforms");
    await expect(page.getByRole("list", { name: "Google Ads stages" })).toContainText(
      "Not provided by the platform",
    );
    await expectAccessible(page, "funnel by platform");
    await page.getByLabel("Show", { exact: true }).selectOption("landing-pages");
    await expect(page.getByRole("heading", { name: "Landing pages" })).toBeVisible();
    await expectAccessible(page, "funnel by landing page");
    pages.push(await page.content());
  });

  await test.step("a campaign strategy shows its amounts and the figures behind it", async () => {
    const { strategyId, productTitle } = createSimulatedStrategy(email, orgUrl);
    await page.getByRole("link", { name: "Strategies", exact: true }).click();
    const row = page.getByRole("row", { name: new RegExp(productTitle) });
    await expect(row).toContainText("Draft");
    await expectAccessible(page, "strategies list");
    await row.getByRole("link", { name: productTitle }).click();
    await expect(page).toHaveURL(new RegExp(`/strategies/${strategyId}$`));
    await expect(page.getByRole("heading", { name: productTitle, level: 1 })).toBeVisible();
    await expect(page.getByText(/Drafted by Claude \(claude-sonnet-5-5\)/)).toBeVisible();
    const google = page.getByRole("heading", { name: /^Google Ads — / }).locator("..");
    await expect(google).toContainText(/\$60\.00 per day \(60% of the budget\)/);
    await expect(google.getByRole("list", { name: "Based on" })).not.toContainText(/: 0$/);
    await expectAccessible(page, "strategy");
    pages.push(await page.content());

    person.expectFailedRequests(422); // a refused edit, and a product that cannot be planned
    person.expectFailedRequests(503); // the planner is off in this installation
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Share of the budget for Google Ads (%)").fill("70");
    await page.getByLabel("Share of the budget for Meta (%)").fill("20");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(
      page.getByRole("form", { name: "Edit the strategy" }).getByRole("alert"),
    ).toContainText("The budget shares do not add up to 100%.");
    await expectAccessible(page, "strategy edit with a failed check");
    await page.getByLabel("Share of the budget for Meta (%)").fill("30");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(google).toContainText(/\$70\.00 per day \(70% of the budget\)/);

    await page.getByRole("button", { name: "Mark ready for the campaign builder" }).click();
    await expect(page.getByText("Ready for the campaign builder")).toBeVisible();
    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive" }).click();
    await expect(page.getByText(/This strategy is archived/)).toBeVisible();
    await expectAccessible(page, "archived strategy");
  });

  await test.step("asking for a strategy when the planner is off says so", async () => {
    await page.getByRole("link", { name: "All strategies" }).click();
    await page.getByRole("combobox", { name: "Product" }).selectOption({ index: 1 });
    await page.getByLabel(/^Budget \(/).fill("50");
    await page.getByRole("button", { name: "Create strategy" }).click();
    await expect(page.getByRole("form", { name: "New strategy" }).getByRole("alert")).toContainText(
      /AI planner is not available right now|cannot be made for this product/,
    );
    await expectAccessible(page, "new strategy refused");
  });

  for (const html of pages) {
    expect(html, "platform tokens never reach a page").not.toMatch(
      /ya29\.|1\/\/sim-refresh|shp(at|rt)_|EAAsim|appsecret_proof/,
    );
  }
});
