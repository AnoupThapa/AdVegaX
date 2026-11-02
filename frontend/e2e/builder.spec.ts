import { createOrganization, registeredUser } from "./support/actions";
import { buildSimulatedCampaign } from "./support/builder";
import { createSimulatedCreatives } from "./support/creatives";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAdsWithConnection } from "./support/google_ads";
import { connectSimulatedStore } from "./support/shopify";
import { createSimulatedStrategy } from "./support/strategy";

/**
 * Phase 10B in the browser (task 10B-07). A Google Ads Search campaign was built from a ready
 * strategy and its approved creative through the Action Engine with the Google Ads simulator:
 * checked, tested by the platform, approved and created **paused**; Go live waits for a second
 * approval. The browser shows the strategy's campaigns, the campaign with its reference and the
 * waiting Go live, and the launch under Changes. A new campaign is then built in the browser;
 * the web server's engine is switched off, so checking it says so and nothing is sent. Every
 * page passes the accessibility check and no platform token ever reaches a page.
 */
test("a campaign is built paused and goes live only after approval", async ({ newPerson }) => {
  test.setTimeout(240_000);
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("builder");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Builder Co");
  loadRecordedRates();
  connectSimulatedStore(email, orgUrl, `e2e-${Date.now().toString(36)}`);
  const { connectionId } = connectSimulatedGoogleAdsWithConnection(email, orgUrl);
  const { strategyId, productTitle } = createSimulatedStrategy(email, orgUrl);
  const pages: string[] = [];

  await page.goto(`${orgUrl}/strategies/${strategyId}`);
  await page.getByRole("button", { name: "Mark ready for the campaign builder" }).click();
  await expect(page.getByText("Ready for the campaign builder")).toBeVisible();
  const setId = createSimulatedCreatives(email, orgUrl, strategyId);
  const built = buildSimulatedCampaign(email, orgUrl, connectionId, strategyId, setId);

  await test.step("the strategy lists its campaign, created paused", async () => {
    await page.reload();
    const section = page.getByRole("region", { name: "Campaigns" });
    await expect(section.getByRole("link", { name: new RegExp(built.reference) })).toBeVisible();
    await expect(section).toContainText("created, paused");
    await expectAccessible(page, "strategy with campaigns");
    pages.push(await page.content());
  });

  await test.step("the campaign shows its reference, paused, and the waiting Go live", async () => {
    await page.goto(`${orgUrl}/builder/${built.draft}`);
    await expect(
      page.getByRole("heading", { level: 1, name: new RegExp(built.reference) }),
    ).toBeVisible();
    await expect(page.getByText(`reference ${built.reference}`, { exact: false })).toBeVisible();
    await expect(
      page.getByText(
        "The campaign exists at the platform, paused. Nothing is spent until it goes live.",
      ),
    ).toBeVisible();
    await expect(
      page.getByText("A change of this campaign is waiting or on its way."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Request Go live" })).toHaveCount(0);
    await expectAccessible(page, "campaign created paused");
    pages.push(await page.content());
  });

  await test.step("the launch and the waiting Go live are under Changes", async () => {
    await page.goto(`${orgUrl}/changes/${built.launch}`);
    await expect(
      page.getByRole("heading", { level: 1, name: /Create the campaign \(paused\)/ }),
    ).toBeVisible();
    await expect(page.getByText(/googleAds:mutate/)).toBeVisible();
    await expectAccessible(page, "launch change");
    await page.goto(`${orgUrl}/changes/${built.goLive}`);
    await expect(page.getByRole("heading", { level: 1, name: /Go live/ })).toBeVisible();
    await expect(page.getByText("Waiting for approval").first()).toBeVisible();
    await expectAccessible(page, "go live waiting");
    pages.push(await page.content());
  });

  await test.step("a new campaign is built; checking it while changes are off says so", async () => {
    await page.goto(`${orgUrl}/strategies/${strategyId}`);
    const section = page.getByRole("region", { name: "Campaigns" });
    await section.getByLabel("Platform").selectOption("google_ads");
    person.expectFailedRequests(422); // building without choosing one of two ad accounts
    await section.getByRole("button", { name: "Build campaign" }).click();
    await expect(section.getByRole("alert")).toContainText(
      "Choose which ad account the campaign is for.",
    );
    await section.getByLabel("Ad account").selectOption({ label: "Eve Zone AU" });
    await section.getByRole("button", { name: "Build campaign" }).click();
    await expect(page).toHaveURL(/\/builder\/[0-9a-f-]+$/);
    await expect(
      page.getByRole("heading", { level: 1, name: new RegExp(productTitle) }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Check and launch" })).toBeVisible();
    await expect(page).toHaveTitle(/^Campaign\b/); // the title follows the client navigation
    await expectAccessible(page, "new campaign draft");
    person.expectFailedRequests(409);
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await expect(
      page.getByRole("region", { name: "Check and launch" }).getByRole("alert"),
    ).toContainText("Changes to ad accounts are switched off");
    await expect(page.getByRole("button", { name: "Request launch" })).toBeDisabled();
    await expectAccessible(page, "campaign draft check refused");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "platform tokens never reach a page").not.toMatch(
      /ya29\.|1\/\/sim-refresh|shp(at|rt)_|EAAsim|appsecret_proof/,
    );
  }
});
