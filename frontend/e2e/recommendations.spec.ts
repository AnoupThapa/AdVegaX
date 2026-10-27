import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAdsWithConnection } from "./support/google_ads";
import { createSimulatedRecommendations } from "./support/recommendations";

/**
 * Phase 11 in the browser (task 11-08). The daily look found two things with AdVegaX's own
 * rules: the AU Search campaign spent every day without a conversion (pause), and the NZ one's
 * cost per conversion tripled (look into it). The pause was approved through the Action Engine
 * with the Google Ads simulator. The browser shows the Recommendations page with the last
 * look, the Overview count, the approved advice and its change under Changes, and rejects the
 * open advice with a reason. Every page passes the accessibility check and no Google token
 * ever reaches a page.
 */
test("recommendations are explained, approved into Changes or rejected", async ({ newPerson }) => {
  test.setTimeout(240_000);
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("recs");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Advice Co");
  loadRecordedRates();
  const { connectionId } = connectSimulatedGoogleAdsWithConnection(email, orgUrl);
  const made = createSimulatedRecommendations(email, orgUrl, connectionId);
  const pages: string[] = [];

  await test.step("the Overview counts the open advice", async () => {
    await page.goto(orgUrl);
    await expect(page.getByText("1 piece of advice waits for your decision.")).toBeVisible();
    await expectAccessible(page, "overview with advice");
  });

  await test.step("the Recommendations page shows the advice and the last look", async () => {
    await page.getByRole("link", { name: "Recommendations", exact: true }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: "Recommendations" })).toBeVisible();
    const list = page.getByRole("list", { name: "Recommendations" });
    await expect(list.getByRole("link", { name: "Cost per conversion jumped" })).toBeVisible();
    await expect(list).toContainText("Proposed: No change: look into it");
    await expect(page.getByText(/running campaigns checked, 2 found/)).toBeVisible();
    await expect(page.getByText(/no store is connected/)).toBeVisible();
    await expectAccessible(page, "recommendations");
    pages.push(await page.content());
  });

  await test.step("the approved advice links to its change", async () => {
    await page.goto(`${orgUrl}/recommendations/${made.approved}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Spend without results" }),
    ).toBeVisible();
    await expect(page.getByText("Pause the campaign", { exact: true })).toBeVisible();
    await expect(page.getByLabel("The figures behind it")).toContainText("Spend");
    await expectAccessible(page, "approved recommendation");
    await page.getByRole("link", { name: "Open it" }).click();
    await expect(page).toHaveURL(new RegExp(`/changes/${made.action}$`));
    await expect(page.getByText("Checked: the platform shows the change.")).toBeVisible();
    pages.push(await page.content());
  });

  await test.step("the open advice is rejected with a reason", async () => {
    await page.goto(`${orgUrl}/recommendations/${made.open}`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Cost per conversion jumped" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Reject" }).click();
    const form = page.getByRole("form", { name: "Reject this advice" });
    await form.getByLabel("Why is it rejected?").selectOption("wrong_time");
    await form.getByLabel("Note (optional)").fill("Sale ends Friday.");
    await expectAccessible(page, "rejecting a recommendation");
    await form.getByRole("button", { name: "Reject this advice" }).click();
    await expect(page.getByText("“Sale ends Friday.”")).toBeVisible();
    await expectAccessible(page, "rejected recommendation");
    pages.push(await page.content());
  });

  await test.step("settings show the thresholds", async () => {
    await page.goto(`${orgUrl}/settings`);
    const form = page.getByRole("form", { name: "Recommendation settings" });
    await expect(form.getByLabel(/Budget step/)).toHaveValue("20");
    await expectAccessible(page, "recommendation settings");
  });

  for (const html of pages) {
    expect(html, "Google tokens never reach a page").not.toMatch(/ya29\.|1\/\/sim-refresh/);
  }
});
