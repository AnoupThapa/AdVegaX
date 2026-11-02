import { createOrganization, registeredUser } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";

/**
 * Phase 14 in the browser (task 14-06). An agency gets its code; a client's owner gives the
 * agency Manager access with it; the agency accepts; the agency's owner opens the client
 * (marked "through" the agency, without its members or billing) and sees it on the Clients
 * page; the client ends the access, and the agency can no longer open it. Accessibility is
 * checked on each page.
 */
test("a client gives an agency access, the agency works in it, and access ends", async ({
  newPerson,
}) => {
  test.setTimeout(180_000);
  const agency = await newPerson("agency");
  const client = await newPerson("client");
  const a = agency.page;
  const c = client.page;
  await registeredUser(a, uniqueEmail("agency"));
  const agencyUrl = await createOrganization(a, "Agency Co");
  await registeredUser(c, uniqueEmail("client"));
  const clientUrl = await createOrganization(c, "Client Co");

  let code = "";
  await test.step("the agency gets its code", async () => {
    await a.goto(`${agencyUrl}/settings`);
    await a.getByRole("button", { name: "Get an agency code" }).click();
    const shown = a.getByText(/Your agency code:/);
    await expect(shown).toBeVisible();
    code = ((await shown.locator("strong").textContent()) ?? "").trim();
    expect(code).toMatch(/^[A-Z0-9]{10}$/);
    await expectAccessible(a, "agency settings with a code");
  });

  await test.step("the client gives access", async () => {
    await c.goto(`${clientUrl}/settings`);
    const form = c.getByRole("form", { name: "Give an agency access" });
    await form.getByLabel(/Agency code/).fill(code);
    await form.getByRole("button", { name: "Give access" }).click();
    await expect(c.getByText(/It starts when the agency accepts it/)).toBeVisible();
    await expect(c.getByRole("list", { name: "Agencies" })).toContainText(
      "waiting for the agency to accept",
    );
    await expectAccessible(c, "client settings with an offer");
  });

  await test.step("the agency accepts and works in the client", async () => {
    await a.reload();
    await a.getByRole("button", { name: "Accept Client Co" }).click();
    await expect(a.getByRole("list", { name: "Clients" })).toContainText("has access");
    await a.getByRole("link", { name: "See all clients" }).click();
    const table = a.getByRole("table", { name: "Clients" });
    await expect(table.getByRole("row", { name: /Client Co/ })).toContainText("Manager");
    await expectAccessible(a, "clients page");
    await table.getByRole("link", { name: "Client Co" }).click();
    await expect(a.getByText(/through Agency Co, as Manager/)).toBeVisible();
    await expectAccessible(a, "client through the agency");
  });

  await test.step("the client ends access", async () => {
    await c.reload();
    await c.getByRole("button", { name: "End access for Agency Co" }).click();
    await expect(c.getByRole("list", { name: "Agencies" })).toContainText("ended");
    await a.goto(clientUrl);
    await expect(a.getByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});
