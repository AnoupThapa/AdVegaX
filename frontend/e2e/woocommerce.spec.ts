import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { connectSimulatedWooStore } from "./support/woocommerce";

/**
 * Phase 2B in the browser (task 2B-09): the WooCommerce connect form explains an unusable
 * address before anything is sent, and a store imported through the WooCommerce simulator is
 * listed with its health warning (Cost of Goods switched off), the orders that count, its
 * figures (never 0 for missing data) and its products. Every page passes the accessibility
 * check, and no store key ever reaches a page.
 */
test("a WooCommerce store connects, imports and explains what needs attention", async ({
  newPerson,
}) => {
  const person = await newPerson("owner");
  const page = person.page;
  const email = uniqueEmail("woo");
  await registeredUser(page, email);
  const orgUrl = await createOrganization(page, "Woo Co");

  await test.step("the connect form refuses an address without HTTPS", async () => {
    await page.goto(`${orgUrl}/connections`);
    const form = page.getByRole("form", { name: "Connect WooCommerce" });
    await expect(page.getByText(/approve read-only access/)).toBeVisible();
    await form.getByLabel(/Store address/).fill("http://shop.example.com");
    await form.getByRole("button", { name: "Connect WooCommerce" }).click();
    await expect(form.getByText(/must use a secure address/)).toBeVisible();
    await expect(page).toHaveURL(`${orgUrl}/connections`); // nothing was sent anywhere
    await expectAccessible(page, "connections (WooCommerce form)");
  });

  const host = `e2e-${Date.now().toString(36)}.example.com`;
  const storeId = connectSimulatedWooStore(email, orgUrl, host, { cogsOff: true });

  await test.step("the Stores tab lists the store", async () => {
    await page.goto(orgUrl);
    await page.getByRole("link", { name: "Stores", exact: true }).click();
    await expect(page.getByRole("link", { name: "Woo Test Store" })).toBeVisible();
    await expect(page.getByText("Up to date")).toBeVisible();
    await expectAccessible(page, "stores (WooCommerce)");
  });

  await test.step("the store page shows its health, counted orders and figures", async () => {
    await page.getByRole("link", { name: "Woo Test Store" }).click();
    await expect(page).toHaveURL(`${orgUrl}/stores/${storeId}`);
    const health = page.getByRole("region", {
      name: "Cost not available — switch on Cost of Goods Sold in WooCommerce",
    });
    await expect(health.getByText(/Settings → Advanced → Features/)).toBeVisible();
    await expect(page.getByText(`https://${host}`)).toBeVisible();
    await expect(page.getByText("WooCommerce version")).toBeVisible();
    await expect(page.getByText(/Counted in the figures: processing, on hold/)).toBeVisible();
    const totals = page.getByRole("list", { name: "Totals for the period" });
    await expect(totals.getByText(/\$29\.91$/)).toBeVisible(); // net sales 48.81 − 18.90
    await expect(totals.getByText(/\$0\.00$/)).toHaveCount(0);
    await expect(totals.getByText("Some products have no cost").first()).toBeVisible();
    await expectAccessible(page, "WooCommerce store");
  });

  await test.step("the products page says why costs are missing", async () => {
    await page.getByRole("link", { name: "Products, stock and costs" }).click();
    await expect(page.getByText(/Cost of Goods Sold is switched off/)).toBeVisible();
    const table = page.getByRole("table");
    await expect(table.getByText("Nitrile Gloves").first()).toBeVisible();
    await expectAccessible(page, "WooCommerce products");
    expect(await page.content(), "store keys never reach the page").not.toMatch(
      /c[ks]_[0-9a-f]{8}/,
    );
  });
});
