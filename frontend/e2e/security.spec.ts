import { createOrganization, registeredUser, submitSignIn } from "./support/actions";
import { uniqueEmail } from "./support/env";
import { expect, expectNoBrowserStorage, test } from "./support/fixtures";

test("every page is served with a nonce-based security policy and safe headers", async ({
  newPerson,
}) => {
  const { page } = await newPerson("visitor");
  for (const path of ["/", "/sign-in", "/sign-up", "/forgot-password"]) {
    const response = await page.goto(path);
    const headers = response?.headers() ?? {};
    const csp = headers["content-security-policy"] ?? "";
    const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
    expect(nonce, `nonce in CSP for ${path}`).toBeTruthy();
    for (const directive of [
      "default-src 'self'",
      "'strict-dynamic'",
      "frame-ancestors 'none'",
      "base-uri 'none'",
      "object-src 'none'",
      "form-action 'self'",
    ]) {
      expect(csp, `${directive} for ${path}`).toContain(directive);
    }
    expect(headers["x-frame-options"]).toBe("DENY");
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toBe("no-referrer");
    const scriptNonces = await page
      .locator("script")
      .evaluateAll((scripts) => scripts.map((s) => (s as HTMLScriptElement).nonce));
    expect(scriptNonces.length).toBeGreaterThan(0);
    expect(new Set(scriptNonces), `every script on ${path} carries this response's nonce`).toEqual(
      new Set([nonce]),
    );
  }
});

test("the CSRF token stays in memory and session cookies are not readable by scripts", async ({
  newPerson,
}) => {
  const { page, context } = await newPerson("user");
  const csrfValues = new Set<string>();
  page.on("request", (request) => {
    const value = request.headers()["x-csrf-token"];
    if (value) csrfValues.add(value);
  });
  await registeredUser(page, uniqueEmail("security"));
  await createOrganization(page, "Security Check Co");
  expect(csrfValues.size, "state-changing requests carry a CSRF token").toBeGreaterThan(0);

  await expectNoBrowserStorage(page, "after sign-in and create organization");
  for (const token of csrfValues) expect(page.url()).not.toContain(token);

  const cookies = await context.cookies();
  expect(cookies.length).toBeGreaterThan(0);
  for (const cookie of cookies) {
    expect(cookie.httpOnly, `${cookie.name} is HttpOnly`).toBe(true);
    expect(["Lax", "Strict"], `${cookie.name} SameSite`).toContain(cookie.sameSite);
  }
});

test("sign-in ignores an unsafe return address", async ({ newPerson }) => {
  const email = uniqueEmail("next");
  const { page } = await newPerson("user");
  await registeredUser(page, email);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/sign-in?next=%2F%2Fevil.example%2Fsteal");
  await submitSignIn(page, email);
  await expect(page).toHaveURL("/");
});
