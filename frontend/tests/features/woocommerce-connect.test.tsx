import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import { STORE_URL_ERRORS, checkStoreUrl } from "@/features/connections/connect-fields";
import { connectError, storeUnreachable } from "@/features/connections/labels";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";
import * as external from "@/lib/navigation/external";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const woocommerce = {
  code: "woocommerce",
  display_name: "WooCommerce",
  category: "commerce",
  auth_scheme: "api_key",
  capabilities: {},
  test_only: false,
};
const AUTHORIZE = "https://shop.example.com/wc-auth/v1/authorize?app_name=AdVegaX&scope=read";

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("WooCommerce store address", () => {
  it.each([
    ["shop.example.com", "https://shop.example.com"],
    ["  Shop.Example.com/ ", "https://shop.example.com"],
    ["https://shop.example.com/wp-admin/", "https://shop.example.com"],
    ["example.com/shop", "https://example.com/shop"],
    ["https://example.com/shop/wp-admin/admin.php?page=wc", "https://example.com/shop"],
    ["https://shop.example.com:443", "https://shop.example.com"],
    ["shop.example.com.", "https://shop.example.com"],
  ])("normalizes %s", (raw, expected) => {
    expect(checkStoreUrl(raw)).toEqual({ value: expected });
  });

  it.each([
    ["", STORE_URL_ERRORS.empty],
    ["http://shop.example.com", STORE_URL_ERRORS.https],
    ["HTTP://shop.example.com", STORE_URL_ERRORS.https],
    ["ftp://shop.example.com", STORE_URL_ERRORS.invalid],
    ["//shop.example.com", STORE_URL_ERRORS.invalid],
    ["shop example.com", STORE_URL_ERRORS.invalid],
    ["localhost", STORE_URL_ERRORS.invalid],
    ["10.0.0.1", STORE_URL_ERRORS.invalid],
    ["-bad.example.com", STORE_URL_ERRORS.invalid],
    ["example.com/../admin", STORE_URL_ERRORS.invalid],
    ["example.com/a%2e%2e", STORE_URL_ERRORS.invalid],
    ["example.com\\shop", STORE_URL_ERRORS.invalid],
    ["https://admin:pw@shop.example.com", STORE_URL_ERRORS.credentials],
    ["shop.example.com:8443", STORE_URL_ERRORS.port],
    ["example.com/a/b/c/d/e/f", STORE_URL_ERRORS.invalid],
  ])("refuses %j with a plain reason", (raw, error) => {
    expect(checkStoreUrl(raw)).toEqual({ error });
  });
});

describe("Connect WooCommerce from the Connections page", () => {
  function render(start: Response = ok({ authorize_url: AUTHORIZE, expires_in_seconds: 600 })) {
    navigation.params = { organizationId: ORG_ID };
    navigation.pathname = `/orgs/${ORG_ID}/connections`;
    const me = testUser();
    const api = mockApi({
      "GET /api/v1/auth/me": ok(me),
      [`GET ${ORG_PATH}`]: ok(testOrg({ role: "manager" })),
      "GET /api/v1/providers": ok([woocommerce]),
      [`GET ${ORG_PATH}/connections`]: ok([]),
      [`POST ${ORG_PATH}/connections/woocommerce/start`]: start,
    });
    renderWithProviders(
      <OrganizationShell>
        <ConnectionsPage />
      </OrganizationShell>,
      { session: me },
    );
    return api;
  }

  it("explains the store's own approval page", async () => {
    render();
    expect(await screen.findByText(/approve read-only access/)).toBeInTheDocument();
    expect(screen.getByText(/never change it/)).toBeInTheDocument();
  });

  it("refuses an address without HTTPS before anything is sent", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = render();
    fill(await screen.findByLabelText(/Store address/), "http://shop.example.com");
    click(screen.getByRole("button", { name: "Connect WooCommerce" }));
    expect(await screen.findByText(STORE_URL_ERRORS.https)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    expect(go).not.toHaveBeenCalled();
  });

  it("sends only the normalized address and goes to the store's approval page", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = render();
    fill(await screen.findByLabelText(/Store address/), "https://Shop.Example.com/wp-admin/");
    click(screen.getByRole("button", { name: "Connect WooCommerce" }));
    await waitFor(() => expect(go).toHaveBeenCalledWith(AUTHORIZE));
    const post = api.calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${ORG_PATH}/connections/woocommerce/start`);
    expect(post?.body).toEqual({ params: { store_url: "https://shop.example.com" } });
    expect(post?.csrf).toBeTruthy();
  });

  it.each([
    ["woocommerce_api_not_found", /WooCommerce's API was not found at this address/],
    ["retryable", /The store did not answer/],
    ["something_new", /could not reach the store's WooCommerce API/],
  ])("explains a store that cannot be used (%s)", async (reason, text) => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    render(fail(422, "STORE_NOT_REACHABLE", [{ reason }]));
    fill(await screen.findByLabelText(/Store address/), "shop.example.com");
    click(screen.getByRole("button", { name: "Connect WooCommerce" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(go).not.toHaveBeenCalled();
  });

  it("shows the store's answer after approval, once, in plain words", async () => {
    navigation.search = "?status=error&code=auth_header_stripped";
    render();
    expect(
      await screen.findByText(/Authorization header through to WordPress/),
    ).toBeInTheDocument();
  });
});

describe("WooCommerce connect messages", () => {
  it.each([
    "key_not_delivered",
    "connect_failed",
    "not_read_only",
    "woocommerce_too_old",
    "key_rejected",
    "auth_header_stripped",
    "woocommerce_api_not_found",
    "store_redirected",
    "unexpected_response",
    "server_error",
    "timeout",
  ])("%s has its own message", (code) => {
    expect(connectError(code)).not.toBe(connectError("unknown_code_x"));
    expect(connectError(code)).not.toContain(code);
  });

  it("old WooCommerce names the version to update to", () => {
    expect(connectError("woocommerce_too_old")).toMatch(/9\.0 or newer/);
    expect(storeUnreachable(undefined)).toMatch(/Check the address/);
  });
});
