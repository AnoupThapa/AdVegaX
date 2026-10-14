import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { connectSimulatedStore } from "./support/shopify";

/**
 * Phase 2A in the browser (task 2A-11): a store imported through the Shopify simulator is
 * listed, its revenue view shows figures with their availability (never 0 for missing data),
 * and its products page shows stock and cost. Every page passes the accessibility check.
 */
test("an imported store's revenue and products are shown with availability", async ({
  newPerson,
}) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("stores");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Store Co");
  const shop = `e2e-${Date.now().toString(36)}`;
  const storeId = connectSimulatedStore(email, orgUrl, shop);

  await test.step("the Stores tab lists the store as up to date", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Stores", exact: true }).click();
    await expect(page.getByRole("link", { name: "Eve Zone Test" })).toBeVisible();
    await expect(page.getByText(`${shop}.myshopify.com · AUD`)).toBeVisible();
    await expect(page.getByText("Up to date")).toBeVisible();
    await expectAccessible(page, "stores (one store)");
  });

  await test.step("the store page shows revenue with availability", async () => {
    await page.getByRole("link", { name: "Eve Zone Test" }).click();
    await expect(page).toHaveURL(`${orgUrl}/stores/${storeId}`);
    await expect(page.getByRole("heading", { level: 1, name: "Eve Zone Test" })).toBeVisible();
    const totals = page.getByRole("list", { name: "Totals for the period" });
    await expect(totals.getByText(/\$29\.91$/)).toBeVisible(); // net sales 48.81 − 18.90 returned
    await expect(totals.getByText("Some products have no cost").first()).toBeVisible();
    await expect(totals.getByText(/\$0\.00$/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Sync now" })).toBeEnabled();
    await expectAccessible(page, "store revenue");
  });

  await test.step("the products page shows stock and cost", async () => {
    await page.getByRole("link", { name: "Products, stock and costs" }).click();
    const table = page.getByRole("table");
    await expect(table.getByText("Nitrile Gloves").first()).toBeVisible();
    await expect(table.getByText("Not tracked")).toBeVisible();
    await expect(table.getByText("Cost when first imported").first()).toBeVisible();
    await page.getByLabel("Search by name or SKU").fill("NG-L");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(table.getByText("Gift Wrap")).toHaveCount(0);
    await expectAccessible(page, "products");
    expect(await page.content(), "platform tokens never reach the page").not.toMatch(/shp(at|rt)_/);
  });
});
