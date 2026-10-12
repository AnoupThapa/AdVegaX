import { connectTestPlatform, createOrganization, registeredUser } from "./support/actions";
import { API, uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";

/** Acceptance criterion 4: nobody sees another organization's data through the UI. */
test("an outsider cannot open another organization's pages", async ({ newPerson }) => {
  const owner = (await newPerson("owner")).page;
  await registeredUser(owner, uniqueEmail("tenant-owner"));
  const orgUrl = await createOrganization(owner, "Private Co");
  const connectionUrl = await connectTestPlatform(owner, orgUrl);

  const outsider = (await newPerson("outsider")).page;
  await registeredUser(outsider, uniqueEmail("tenant-outsider"));

  for (const url of [
    orgUrl,
    `${orgUrl}/members`,
    `${orgUrl}/settings`,
    `${orgUrl}/connections`,
    connectionUrl,
  ]) {
    await outsider.goto(url);
    await expect(outsider.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(outsider.getByText("Private Co")).toHaveCount(0);
  }
  await expectAccessible(outsider, "another organization (not found)");

  const orgId = new URL(orgUrl).pathname.split("/")[2];
  const status = await outsider.evaluate(
    async ([api, id]) =>
      (await fetch(`${api}/organizations/${id}`, { credentials: "include" })).status,
    [API, orgId] as const,
  );
  expect(status, "the API answers 404, not 403, for non-members").toBe(404);
});

test("a signed-out visitor is sent to sign in and back", async ({ newPerson }) => {
  const visitor = (await newPerson("visitor")).page;
  await visitor.goto("/orgs/00000000-0000-4000-8000-000000000000/members");
  await expect(visitor).toHaveURL(
    /\/sign-in\?next=%2Forgs%2F00000000-0000-4000-8000-000000000000%2Fmembers$/,
  );
});
