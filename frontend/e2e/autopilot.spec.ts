import { createOrganization, registeredUser } from "./support/actions";
import { createAutopilotChange } from "./support/autopilot";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAdsWithConnection } from "./support/google_ads";

/**
 * Phase 12 in the browser (task 12-07). After a person's approved change made the organization
 * ready, the owner switched autopilot on for the NZ account and autopilot paused that campaign
 * through the Action Engine with the Google Ads simulator. The browser shows autopilot on (the
 * Overview banner, Settings → Autopilot with its run), the change under Changes "made by
 * autopilot", and stops autopilot with one click. Every page passes the accessibility check and
 * no Google token ever reaches a page.
 */
test("autopilot acts within limits, is shown everywhere and stops at once", async ({
  newPerson,
}) => {
  test.setTimeout(240_000);
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("auto");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Auto Co");
  loadRecordedRates();
  const { connectionId } = connectSimulatedGoogleAdsWithConnection(email, orgUrl);
  const made = createAutopilotChange(email, orgUrl, connectionId);
  const pages: string[] = [];

  await test.step("the Overview says autopilot is on", async () => {
    await page.goto(orgUrl);
    await expect(page.getByText(/Autopilot is on: AdVegaX may pause campaigns/)).toBeVisible();
    await expectAccessible(page, "overview with autopilot on");
  });

  await test.step("the change is under Changes, made by autopilot", async () => {
    await page.goto(`${orgUrl}/changes`);
    await page.getByLabel("Show").selectOption("");
    await expect(page.getByText("(made by autopilot)").first()).toBeVisible();
    await page.goto(`${orgUrl}/changes/${made.action}`);
    await expect(page.getByText(/by autopilot, within the limits an owner set/)).toBeVisible();
    await expect(page.getByText("Checked: the platform shows the change.")).toBeVisible();
    await expect(page.getByRole("link", { name: "See the advice" })).toHaveAttribute(
      "href",
      new RegExp(`/recommendations/${made.recommendation}$`),
    );
    await expectAccessible(page, "change made by autopilot");
    pages.push(await page.content());
  });

  await test.step("Settings show autopilot, its run, and stop it", async () => {
    await page.goto(`${orgUrl}/settings`);
    await expect(page.getByText(/Autopilot is on since/)).toBeVisible();
    await expect(page.getByRole("table", { name: "Recent autopilot runs" })).toBeVisible();
    await expect(page.getByRole("form", { name: "Autopilot policy" })).toBeVisible();
    await expectAccessible(page, "autopilot settings");
    await page.getByRole("button", { name: "Stop autopilot" }).click();
    await expect(page.getByText(/Stopped by a person/)).toBeVisible();
    await expectAccessible(page, "autopilot stopped");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "Google tokens never reach a page").not.toMatch(/ya29\.|1\/\/sim-refresh/);
  }
});
