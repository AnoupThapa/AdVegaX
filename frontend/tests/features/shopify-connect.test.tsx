import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import { InstallLanding } from "@/features/connections/InstallLanding";
import { normalizeShopDomain } from "@/features/connections/connect-fields";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";
import * as external from "@/lib/navigation/external";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const OTHER_ORG = "11111111-2222-4333-8444-555555555555";
const shopify = {
  code: "shopify",
  display_name: "Shopify",
  category: "commerce",
  auth_scheme: "oauth2",
  capabilities: {},
  test_only: false,
};
const AUTHORIZE = "https://eve-zone.myshopify.com/admin/oauth/authorize?state=s";

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("store address", () => {
  it("accepts what people paste and rejects anything else", () => {
    expect(normalizeShopDomain("eve-zone")).toBe("eve-zone.myshopify.com");
    expect(normalizeShopDomain("  Eve-Zone.myshopify.com ")).toBe("eve-zone.myshopify.com");
    expect(normalizeShopDomain("https://eve-zone.myshopify.com/admin?x=1")).toBe(
      "eve-zone.myshopify.com",
    );
    for (const bad of [
      "",
      "   ",
      "eve zone",
      "evil.com",
      "-x.myshopify.com",
      "a.myshopify.com.evil",
    ]) {
      expect(normalizeShopDomain(bad)).toBeNull();
    }
  });
});

describe("Connect Shopify from the Connections page", () => {
  function render() {
    navigation.params = { organizationId: ORG_ID };
    navigation.pathname = `/orgs/${ORG_ID}/connections`;
    const me = testUser();
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [`GET ${ORG_PATH}`]: ok(testOrg({ role: "manager" })),
      "GET /api/v1/providers": ok([shopify]),
      [`GET ${ORG_PATH}/connections`]: ok([]),
      [`POST ${ORG_PATH}/connections/shopify/start`]: ok({
        authorize_url: AUTHORIZE,
        expires_in_seconds: 600,
      }),
    });
    renderWithProviders(
      <OrganizationShell>
        <ConnectionsPage />
      </OrganizationShell>,
      { session: me },
    );
    return api;
  }

  it("asks for the store address and checks it before leaving", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = render();
    const input = await screen.findByLabelText(/Store address/);
    fill(input, "not a store");
    click(screen.getByRole("button", { name: "Connect Shopify" }));
    expect(await screen.findByText(/Enter a store address like/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    expect(go).not.toHaveBeenCalled();
  });

  it("sends only the normalised store address and goes to Shopify", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = render();
    fill(await screen.findByLabelText(/Store address/), "https://Eve-Zone.myshopify.com/admin");
    click(screen.getByRole("button", { name: "Connect Shopify" }));
    await waitFor(() => expect(go).toHaveBeenCalledWith(AUTHORIZE));
    const post = api.calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${ORG_PATH}/connections/shopify/start`);
    expect(post?.body).toEqual({ params: { shop_domain: "eve-zone.myshopify.com" } });
    expect(post?.csrf).toBeTruthy();
  });
});

describe("Install landing", () => {
  function land(search: string, memberships: unknown[] = [], provider = "shopify") {
    navigation.params = { provider };
    navigation.pathname = `/connect/${provider}`;
    navigation.search = search;
    const me = testUser({ memberships } as never);
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      "GET /api/v1/providers": ok([shopify]),
      [`POST ${ORG_PATH}/connections/shopify/start`]: ok({
        authorize_url: AUTHORIZE,
        expires_in_seconds: 600,
      }),
      [`POST /api/v1/organizations/${OTHER_ORG}/connections/shopify/start`]: fail(403, "FORBIDDEN"),
    });
    renderWithProviders(<InstallLanding />, { session: me });
    return api;
  }
  const member = (id: string, name: string, role: string) => ({
    organization_id: id,
    organization_name: name,
    organization_slug: name.toLowerCase(),
    role,
  });

  it("refuses an incomplete or unknown install link", () => {
    land("");
    expect(screen.getByText(/install link is incomplete or not valid/)).toBeInTheDocument();
  });

  it("refuses an unknown platform", () => {
    land("?account=eve-zone.myshopify.com", [], "other");
    expect(screen.getByText(/install link is incomplete or not valid/)).toBeInTheDocument();
  });

  it("explains when the person cannot connect a store anywhere", async () => {
    land("?account=eve-zone.myshopify.com", [member(OTHER_ORG, "Mediflex", "viewer")]);
    expect(await screen.findByText(/owner, admin or manager/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue/ })).toBeNull();
  });

  it("offers only organizations the person can manage, then goes to Shopify", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = land("?account=eve-zone.myshopify.com", [
      member(OTHER_ORG, "Mediflex", "viewer"),
      member(ORG_ID, "Eve Zone", "owner"),
    ]);
    expect(screen.getByText("eve-zone.myshopify.com")).toBeInTheDocument();
    const select = screen.getByLabelText("Organization") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual([ORG_ID]);
    click(await screen.findByRole("button", { name: "Continue to Shopify" }));
    await waitFor(() => expect(go).toHaveBeenCalledWith(AUTHORIZE));
    const post = api.calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${ORG_PATH}/connections/shopify/start`);
    expect(post?.body).toEqual({ params: { shop_domain: "eve-zone.myshopify.com" } });
  });

  it("shows an error when the platform address is refused", async () => {
    vi.spyOn(external, "goToExternal").mockReturnValue(false);
    land("?account=eve-zone", [member(ORG_ID, "Eve Zone", "admin")]);
    click(await screen.findByRole("button", { name: "Continue to Shopify" }));
    expect(await screen.findByText(/Something went wrong/)).toBeInTheDocument();
  });
});
