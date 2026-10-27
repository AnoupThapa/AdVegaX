import { createOrganization, registeredUser } from "./support/actions";
import { createSimulatedChanges } from "./support/changes";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { loadRecordedRates } from "./support/fx";
import { connectSimulatedGoogleAdsWithConnection } from "./support/google_ads";

/**
 * Phase 10A in the browser (task 10A-07). A daily budget change was made through the Action
 * Engine with the Google Ads simulator (checked, tested by the platform, approved, sent, read
 * back and verified) and its undo waits for approval. The browser shows the Changes page, the
 * change with exactly what was sent, its verification and history, the waiting undo, the
 * campaign's own changes, the settings and the connection's "Allow changes". The web server's
 * engine is switched off, so asking for a change in the browser says so and nothing is sent.
 * Every page passes the accessibility check and no Google token ever reaches a page.
 */
test("changes to ad accounts are checked, approved, verified and shown", async ({ newPerson }) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("changes");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Changes Co");
  loadRecordedRates();
  const { connectionId } = connectSimulatedGoogleAdsWithConnection(email, orgUrl);
  const made = createSimulatedChanges(email, orgUrl, connectionId);
  const pages: string[] = [];

  await test.step("the Changes page lists what was done and what waits", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Changes", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Changes" })).toBeVisible();
    const waiting = page.getByRole("table", { name: "Changes, newest first" });
    await expect(waiting.getByText("Waiting for approval")).toBeVisible();
    await page.getByLabel("Show").selectOption("");
    await expect(
      page.getByRole("link", { name: /Daily budget from A?\$60\.00 to A?\$50\.00/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Daily budget from A?\$50\.00 to A?\$60\.00/ }),
    ).toBeVisible();
    await expectAccessible(page, "changes");
    pages.push(await page.content());
  });

  await test.step("a change shows what was sent, its verification and history", async () => {
    await page.goto(`${orgUrl}/changes/${made.done}`);
    await expect(
      page.getByRole("heading", { level: 1, name: /Daily budget from A?\$50\.00 to A?\$60\.00/ }),
    ).toBeVisible();
    await expect(page.getByText("Checked: the platform shows the change.")).toBeVisible();
    await expect(page.getByText(/campaignBudgets:mutate/)).toBeVisible();
    await expect(page.getByText(/"amountMicros": "60000000"/)).toBeVisible();
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
    await expectAccessible(page, "change done");
    pages.push(await page.content());
  });

  await test.step("approving while the engine is off says so; nothing is sent", async () => {
    await page.goto(`${orgUrl}/changes/${made.undo}`);
    await expect(page.getByText("Waiting for approval")).toBeVisible();
    await page.getByRole("button", { name: "Approve and send" }).click();
    await expect(page.getByRole("alert")).toContainText("Changes to ad accounts are switched off");
    await person.expectFailedRequests(409);
    await expectAccessible(page, "change waiting");
    pages.push(await page.content());
  });

  await test.step("the campaign shows its changes", async () => {
    await page.goto(`${orgUrl}/advertising/campaigns/${made.campaign}`);
    const section = page.getByRole("region", { name: "Changes" });
    await expect(section.getByText(/A change of this campaign is in progress/)).toBeVisible();
    await expect(
      section.getByRole("list", { name: "Recent changes of this campaign" }),
    ).toBeVisible();
    await expectAccessible(page, "campaign with changes");
    pages.push(await page.content());
  });

  await test.step("settings and the connection show the rules and the access", async () => {
    await page.goto(`${orgUrl}/settings`);
    const form = page.getByRole("form", { name: "Change settings" });
    await expect(
      page.getByText(/Changes are switched off for this AdVegaX installation/),
    ).toBeVisible();
    await expect(form.getByLabel(/Maximum daily budget per campaign/)).toHaveValue("500.00");
    await expectAccessible(page, "change settings");
    await page.goto(`${orgUrl}/connections/${connectionId}`);
    await expect(
      page.getByRole("heading", { name: "Changes through this connection" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Stop allowing changes" })).toBeVisible();
    await expectAccessible(page, "connection with changes allowed");
    pages.push(await page.content());
  });

  for (const html of pages) {
    expect(html, "Google tokens never reach a page").not.toMatch(/ya29\.|1\/\/sim-refresh/);
  }
});
