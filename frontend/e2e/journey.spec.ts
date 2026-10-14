import {
  connectTestPlatform,
  createOrganization,
  signIn,
  signUp,
  submitSignIn,
  verifyEmail,
} from "./support/actions";
import { API, uniqueEmail } from "./support/env";
import { expect, expectAccessible, test } from "./support/fixtures";
import { emailLink } from "./support/mail";

/**
 * The Phase 1 journey (PHASE_01C_PLAN §1, §9) with an accessibility check on every page:
 * sign up → verify → sign in → create organization → invite → accept as a second person →
 * change role → connect the test platform → link → sync → unlink → disconnect → sign out.
 */
test("the full Phase 1 journey works for an owner and an invited member", async ({ newPerson }) => {
  const ownerEmail = uniqueEmail("owner");
  const memberEmail = uniqueEmail("member");
  const owner = await newPerson("owner");
  const a = owner.page;

  await test.step("owner signs up and verifies their email address", async () => {
    await a.goto("/");
    await expectAccessible(a, "home (signed out)");
    await a.goto("/sign-up");
    await expectAccessible(a, "sign up");
    await a.getByRole("button", { name: "Create account" }).click();
    await expect(a.getByLabel("Email", { exact: true })).toBeFocused();
    await expectAccessible(a, "sign up with errors");
    await signUp(a, ownerEmail);
    await expectAccessible(a, "check your email");
    await verifyEmail(a, ownerEmail);
    await expectAccessible(a, "email verified");
  });

  await test.step("owner signs in (a wrong password is refused first)", async () => {
    await a.goto("/sign-in");
    await expectAccessible(a, "sign in");
    await submitSignIn(a, ownerEmail, "not the right password");
    await expect(a.getByRole("alert").filter({ hasText: /\S/ })).toBeVisible();
    await signIn(a, ownerEmail);
    await expect(
      a.locator("#main").getByText("You are not in any organization yet.", { exact: false }),
    ).toBeVisible();
    await expectAccessible(a, "home (no organizations)");
  });

  let orgUrl = "";
  await test.step("owner creates an organization and changes its settings", async () => {
    await a.goto("/orgs/new");
    await expectAccessible(a, "create organization");
    orgUrl = await createOrganization(a, "Journey Test Co");
    await expect(a.getByText("Your role: Owner")).toBeVisible();
    await expectAccessible(a, "organization overview");
    await a.goto(`${orgUrl}/settings`);
    await expectAccessible(a, "organization settings");
    await a.getByLabel("Organization name").fill("Journey Test Company");
    await a.getByRole("button", { name: "Save changes" }).click();
    await expect(a.getByRole("status").filter({ hasText: /saved/i })).toBeVisible();
  });

  await test.step("owner invites a member as Manager", async () => {
    await a.goto(`${orgUrl}/members`);
    await expectAccessible(a, "members (owner)");
    const form = a.getByRole("form", { name: "Invite a member" });
    await form.getByLabel("Email address").fill(memberEmail);
    await form.getByLabel("Role", { exact: true }).selectOption("manager");
    await form.getByRole("button", { name: "Send invitation" }).click();
    await expect(a.getByText(`Invitation sent to ${memberEmail}.`, { exact: false })).toBeVisible();
    await expectAccessible(a, "members with a pending invitation");
  });

  const member = await newPerson("member");
  const b = member.page;
  await test.step("the invited person signs up, opens the invitation and accepts it", async () => {
    await signUp(b, memberEmail);
    await verifyEmail(b, memberEmail);
    await b.goto(await emailLink(memberEmail, "invitations/accept"));
    await expect(b, "invitation token removed from the address").not.toHaveURL(/token/);
    const signInLink = b.locator("#main").getByRole("link", { name: "Sign in" });
    await expect(signInLink).toBeVisible();
    await expectAccessible(b, "accept invitation (signed out)");
    await signInLink.click();
    await expect(b).toHaveURL(/\/sign-in\?next=/);
    await submitSignIn(b, memberEmail);
    await expect(b).toHaveURL("/invitations/accept");
    await expectAccessible(b, "accept invitation (signed in)");
    await b.getByRole("button", { name: "Accept invitation" }).click();
    await expect(b).toHaveURL(orgUrl);
    await expect(b.getByText("Your role: Manager")).toBeVisible();
  });

  await test.step("owner changes the member to Viewer; the viewer sees no change controls", async () => {
    await a.goto(`${orgUrl}/members`);
    await a.getByRole("combobox", { name: `Role for ${memberEmail}` }).selectOption("viewer");
    await a.getByRole("button", { name: `Save role for ${memberEmail}` }).click();
    await expect(a.getByText(`${memberEmail} is now Viewer.`)).toBeVisible();

    await b.goto(`${orgUrl}/members`);
    await expect(b.getByRole("table")).toBeVisible();
    await expect(b.getByRole("button", { name: /^Remove / })).toHaveCount(0);
    await expect(b.getByRole("form", { name: "Invite a member" })).toHaveCount(0);
    await expectAccessible(b, "members (viewer)");
  });

  let connectionUrl = "";
  await test.step("owner connects the test platform and accounts are found", async () => {
    await a.goto(`${orgUrl}/connections`);
    await expect(a.getByText("Nothing is connected yet.")).toBeVisible();
    await expectAccessible(a, "connections (empty)");
    connectionUrl = await connectTestPlatform(a, orgUrl);
    await expect(a.getByRole("table", { name: /3 accounts/ })).toBeVisible({ timeout: 60_000 });
    await expectAccessible(a, "connection detail");
  });

  await test.step("owner links an account, syncs it, views history and unlinks it", async () => {
    await a.getByRole("button", { name: "Link Fake Account 101" }).click();
    await expect(a.getByRole("button", { name: "Unlink Fake Account 101" })).toBeVisible();
    const row = a.getByRole("row", { name: /Fake Account 101/ });
    await expect(row.getByText("Not synced yet")).toBeVisible();
    await a.getByRole("button", { name: "Sync Fake Account 101 now" }).click();
    await expect(row.getByText("Sync: Finished")).toBeVisible({ timeout: 60_000 });
    await expect(row.getByText("Not synced yet")).toHaveCount(0);
    await a.getByRole("button", { name: "Show link history for Fake Account 101" }).click();
    await expect(
      a.getByRole("button", { name: "Hide link history for Fake Account 101" }),
    ).toBeVisible();
    await expectAccessible(a, "connection detail with history");
    await a.getByRole("button", { name: "Unlink Fake Account 101" }).click();
    await expect(a.getByRole("button", { name: "Link Fake Account 101" })).toBeVisible();
  });

  await test.step("the viewer can see the connection but cannot change it", async () => {
    await b.goto(connectionUrl);
    await expect(b.getByRole("table", { name: /3 accounts/ })).toBeVisible();
    await expect(
      b.getByRole("button", { name: /^(Link|Unlink|Sync|Disconnect|Check)/ }),
    ).toHaveCount(0);
    await expectAccessible(b, "connection detail (viewer)");
  });

  await test.step("the Stores tab explains how to add a store", async () => {
    await a.goto(orgUrl);
    await a.getByRole("link", { name: "Stores" }).click();
    await expect(a).toHaveURL(`${orgUrl}/stores`);
    await expect(a.getByText("No stores yet.")).toBeVisible();
    await expectAccessible(a, "stores (empty)");
  });

  await test.step("owner disconnects the platform after confirming", async () => {
    await a.goto(connectionUrl);
    await a.getByRole("button", { name: /^Disconnect Test platform/ }).click();
    const dialog = a.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expectAccessible(a, "disconnect confirmation");
    await dialog.getByRole("button", { name: "Disconnect" }).click();
    await expect(a).toHaveURL(`${orgUrl}/connections`);
    await expect(a.getByText("Disconnected", { exact: true })).toBeVisible();
    expect(await a.content(), "platform tokens never reach the page").not.toMatch(/fake-(at|rt)-/);
  });

  await test.step("owner signs out and the API agrees the session has ended", async () => {
    await a.getByRole("button", { name: "Sign out" }).click();
    await expect(a).toHaveURL("/sign-in");
    const status = await a.evaluate(
      async (api) => (await fetch(`${api}/auth/me`, { credentials: "include" })).status,
      API,
    );
    expect(status).toBe(401);
  });
});
