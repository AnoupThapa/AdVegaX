import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { ProductsPage } from "@/features/stores/ProductsPage";
import { StorePage } from "@/features/stores/StorePage";
import { StoresPage } from "@/features/stores/StoresPage";
import { formatDay } from "@/features/stores/dates";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const STORE = "5d1c2b3a-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const me = testUser();

const store = (extra: Record<string, unknown> = {}, sync: Record<string, unknown> = {}) => ({
  id: STORE,
  resource_id: "r-1",
  provider: "shopify",
  domain: "eve-zone.myshopify.com",
  name: "Eve Zone",
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  status: "active",
  linked: true,
  connection_status: "active",
  history_from: "2026-08-15T00:00:00Z",
  first_import_completed_at: "2026-10-13T00:00:00Z",
  created_at: "2026-10-13T00:00:00Z",
  sync: {
    running: false,
    mode: null,
    progress: null,
    last_reconciled_at: "2026-10-14T01:00:00Z",
    last_deep_reconciled_at: null,
    last_error_code: null,
    last_error_at: null,
    ...sync,
  },
  ...extra,
});

const figure = (
  value: string | null,
  availability = "available",
  reason: string | null = null,
) => ({
  value,
  availability,
  reason,
});

const day = (date: string, extra: Record<string, unknown> = {}) => ({
  day: date,
  availability: "available",
  gross_sales: "50.810000",
  discounts: "2.000000",
  sales_reversals: "0",
  net_sales: "48.810000",
  shipping: "9.080000",
  taxes: "5.800000",
  duties: "0",
  fees: "0",
  total_sales: "63.690000",
  orders_count: 1,
  cogs: figure(null, "unavailable", "missing_product_costs"),
  gross_profit: figure(null, "unavailable", "missing_product_costs"),
  cost_coverage: figure("0.774431"),
  ...extra,
});

const unsynced = (date: string) =>
  day(date, {
    availability: "not_synchronized",
    gross_sales: null,
    discounts: null,
    sales_reversals: null,
    net_sales: null,
    shipping: null,
    taxes: null,
    duties: null,
    fees: null,
    total_sales: null,
    orders_count: null,
    cogs: figure(null, "not_synchronized", "not_synchronized"),
    gross_profit: figure(null, "not_synchronized", "not_synchronized"),
    cost_coverage: figure(null, "not_synchronized", "not_synchronized"),
  });

const metrics = (extraTotals: Record<string, unknown> = {}, days = [day("2026-10-05")]) => ({
  store_id: STORE,
  definition_version: "finance-v1",
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  from_day: "2026-09-15",
  to_day: "2026-10-14",
  synced_from: "2026-08-16",
  days,
  totals: {
    availability: "available",
    gross_sales: "50.810000",
    discounts: "2.000000",
    sales_reversals: "18.900000",
    net_sales: "29.910000",
    shipping: "9.080000",
    taxes: "3.910000",
    duties: "0",
    fees: "0",
    total_sales: "42.900000",
    orders_count: 1,
    cogs: figure(null, "unavailable", "missing_product_costs"),
    gross_profit: figure(null, "unavailable", "missing_product_costs"),
    gross_margin: figure(null, "unavailable", "missing_product_costs"),
    cost_coverage: figure("0.632564"),
    shipping_cost: figure(null, "unsupported", "not_provided_by_platform"),
    payment_fees: figure(null, "unsupported", "not_provided_by_platform"),
    new_vs_returning: figure(null, "unavailable", "customer_key_not_collected"),
    ...extraTotals,
  },
});

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function inShell(ui: React.ReactElement, path: string, params: Record<string, string> = {}) {
  navigation.params = { organizationId: ORG_ID, ...params };
  navigation.pathname = path;
  return <OrganizationShell>{ui}</OrganizationShell>;
}

function baseApi(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...extra,
  });
}

const STORE_PATH = `${ORG_PATH}/stores/${STORE}`;

describe("Stores list", () => {
  it("shows stores with plain status and sync state, and a Stores tab", async () => {
    baseApi("owner", {
      [`GET ${ORG_PATH}/stores`]: ok([
        store(),
        store(
          {
            id: "s2",
            name: null,
            domain: "mediflex.myshopify.com",
            status: "importing",
            first_import_completed_at: null,
          },
          { running: true, mode: "initial", progress: 40 },
        ),
      ]),
    });
    renderWithProviders(inShell(<StoresPage />, `/orgs/${ORG_ID}/stores`), { session: me });
    expect(await screen.findByRole("heading", { level: 1, name: "Stores" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Organization" });
    expect(within(nav).getByRole("link", { name: "Stores" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("link", { name: "Eve Zone" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/stores/${STORE}`,
    );
    expect(screen.getByText("Up to date")).toBeInTheDocument();
    expect(screen.getByText(/Last checked:/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "mediflex.myshopify.com" })).toBeInTheDocument();
    expect(screen.getByText(/Importing your products and orders \(40%\)/)).toBeInTheDocument();
    expect(screen.getByText("Importing")).toBeInTheDocument();
  });

  it("explains how to add a store when there is none", async () => {
    baseApi("viewer", { [`GET ${ORG_PATH}/stores`]: ok([]) });
    renderWithProviders(inShell(<StoresPage />, `/orgs/${ORG_ID}/stores`), { session: me });
    expect(await screen.findByText("No stores yet.")).toBeInTheDocument();
    const empty = screen.getByText("No stores yet.").closest("section, div") as HTMLElement;
    expect(within(empty).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
  });

  it("shows sync problems in plain words", async () => {
    baseApi("owner", {
      [`GET ${ORG_PATH}/stores`]: ok([
        store({ linked: false }),
        store(
          { id: "s3", name: "Broken", connection_status: "expired" },
          { last_error_code: "access_denied" },
        ),
      ]),
    });
    renderWithProviders(inShell(<StoresPage />, `/orgs/${ORG_ID}/stores`), { session: me });
    expect(await screen.findByText("Not linked")).toBeInTheDocument();
    expect(screen.getByText("Needs reconnecting")).toBeInTheDocument();
    expect(screen.getByText(/Shopify refused access to the data/)).toBeInTheDocument();
  });
});

describe("Store page and revenue", () => {
  function storeApi(role = "manager", extra: Parameters<typeof mockApi>[0] = {}) {
    return baseApi(role, {
      [`GET ${STORE_PATH}`]: ok(store()),
      [`GET ${STORE_PATH}/metrics/daily`]: ok(metrics()),
      ...extra,
    });
  }

  it("shows store facts and figures with availability, never 0 for missing data", async () => {
    storeApi();
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByRole("heading", { level: 1, name: "Eve Zone" })).toBeInTheDocument();
    expect(screen.getByText("eve-zone.myshopify.com")).toBeInTheDocument();
    const totals = await screen.findByRole("list", { name: "Totals for the period" });
    expect(within(totals).getByText(/\$29\.91$/)).toBeInTheDocument(); // net sales
    expect(within(totals).getByText(/\$42\.90$/)).toBeInTheDocument(); // total sales
    expect(within(totals).getAllByText("Some products have no cost").length).toBeGreaterThan(0);
    expect(within(totals).getByText(/Cost known for 63.3% of net sales/)).toBeInTheDocument();
    expect(screen.getByLabelText("Breakdown")).toBeInTheDocument();
    expect(screen.getAllByText("Not provided by the platform")).toHaveLength(2);
    expect(screen.getByText("Not collected yet")).toBeInTheDocument();
    const table = screen.getByRole("table");
    const row = within(table).getByRole("row", { name: new RegExp(formatDay("2026-10-05")) });
    expect(within(row).getByText(/\$48\.81$/)).toBeInTheDocument();
    expect(within(row).getByText(/\$63\.69$/)).toBeInTheDocument();
    expect(screen.getByText(/definition finance-v1/)).toBeInTheDocument();
  });

  it("does not total a period with unsynced days", async () => {
    storeApi("viewer", {
      [`GET ${STORE_PATH}/metrics/daily`]: ok(
        metrics(
          {
            availability: "not_synchronized",
            net_sales: null,
            total_sales: null,
            orders_count: null,
            gross_profit: figure(null, "not_synchronized", "not_synchronized"),
            gross_margin: figure(null, "not_synchronized", "not_synchronized"),
            cost_coverage: figure(null, "not_synchronized", "not_synchronized"),
          },
          [unsynced("2026-08-15"), day("2026-08-16")],
        ),
      ),
    });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByText(/period totals are not shown/)).toBeInTheDocument();
    const totals = screen.getByRole("list", { name: "Totals for the period" });
    expect(within(totals).queryByText(/\$0\.00/)).toBeNull();
    expect(within(totals).getAllByText("Not synced yet").length).toBeGreaterThanOrEqual(3);
    const row = screen.getByRole("row", { name: new RegExp(formatDay("2026-08-15")) });
    expect(within(row).getAllByText("Not synced yet").length).toBe(4);
    // Viewers cannot sync.
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("shows days with orders in other currencies as not available, never as 0", async () => {
    const other = "other_currency_orders";
    const foreign = day("2026-10-06", {
      ...unsynced("2026-10-06"),
      availability: "unavailable",
      reason: other,
      cogs: figure(null, "unavailable", other),
      gross_profit: figure(null, "unavailable", other),
      cost_coverage: figure(null, "unavailable", other),
    });
    storeApi("viewer", {
      [`GET ${STORE_PATH}/metrics/daily`]: ok(
        metrics(
          {
            availability: "unavailable",
            reason: other,
            gross_sales: null,
            discounts: null,
            sales_reversals: null,
            net_sales: null,
            shipping: null,
            taxes: null,
            duties: null,
            fees: null,
            total_sales: null,
            orders_count: null,
            cogs: figure(null, "unavailable", other),
            gross_profit: figure(null, "unavailable", other),
            gross_margin: figure(null, "unavailable", other),
            cost_coverage: figure(null, "unavailable", other),
          },
          [day("2026-10-05"), foreign],
        ),
      ),
    });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByText(/orders in another currency/)).toBeInTheDocument();
    const label = "Not available — orders in other currencies";
    const totals = screen.getByRole("list", { name: "Totals for the period" });
    expect(within(totals).queryByText(/\$0\.00/)).toBeNull();
    expect(within(totals).queryByText("Not synced yet")).toBeNull();
    expect(within(totals).getAllByText(label).length).toBeGreaterThanOrEqual(3);
    const row = screen.getByRole("row", { name: new RegExp(formatDay("2026-10-06")) });
    expect(within(row).getAllByText(label)).toHaveLength(4);
    const counted = screen.getByRole("row", { name: new RegExp(formatDay("2026-10-05")) });
    expect(within(counted).getByText(/\$63\.69$/)).toBeInTheDocument();
  });

  it("changes the period", async () => {
    const api = storeApi();
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    const select = await screen.findByLabelText("Period");
    fill(select, "7");
    await waitFor(() =>
      expect(
        api.calls.filter((c) => c.path === `${STORE_PATH}/metrics/daily`).length,
      ).toBeGreaterThanOrEqual(2),
    );
  });

  it("Sync now starts a full check, and explains a refusal", async () => {
    const api = storeApi("manager", {
      [`POST ${STORE_PATH}/resync`]: ok({ store_id: STORE, job_id: "j", mode: "deep" }, 202),
    });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByText(/Full check started/)).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST" && c.path === `${STORE_PATH}/resync`);
    expect(post?.csrf).toBe("csrf-test");
    api.set(`POST ${STORE_PATH}/resync`, fail(409, "SYNC_IN_PROGRESS"));
    click(screen.getByRole("button", { name: "Sync now" }));
    expect(await screen.findByText(/already being updated/)).toBeInTheDocument();
  });

  it("disables Sync now while an update runs, and hides it for unlinked stores", async () => {
    storeApi("owner", {
      [`GET ${STORE_PATH}`]: ok(store({}, { running: true, mode: "reconcile" })),
    });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByRole("button", { name: "Sync now" })).toBeDisabled();
    expect(screen.getByText(/Checking for changes now/)).toBeInTheDocument();
  });

  it("unlinked store: no Sync now, and a hint to link it", async () => {
    storeApi("owner", { [`GET ${STORE_PATH}`]: ok(store({ linked: false })) });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByText(/This store is not linked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("unknown or malformed store ids show not found", async () => {
    baseApi("owner", { [`GET ${STORE_PATH}`]: fail(404, "NOT_FOUND") });
    const { unmount } = renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByRole("heading", { name: "Store not found" })).toBeInTheDocument();
    unmount();
    const api = baseApi("owner");
    renderWithProviders(inShell(<StorePage />, `/orgs/${ORG_ID}/stores/x`, { storeId: "x" }), {
      session: me,
    });
    expect(await screen.findByRole("heading", { name: "Store not found" })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.includes("/stores/"))).toBe(false);
  });
});

describe("Products", () => {
  const variant = (extra: Record<string, unknown> = {}) => ({
    id: "v1",
    external_id: "gid://shopify/ProductVariant/11",
    title: "Medium",
    sku: "NG-M",
    price: "19.900000",
    deleted: false,
    inventory: {
      availability: "available",
      tracked: true,
      available: 120,
      synced_at: "2026-10-13T00:00:00Z",
    },
    cost: {
      availability: "available",
      unit_cost: "7.250000",
      source: "import_snapshot",
      effective_from: "2026-10-13T00:00:00Z",
      reason: null,
    },
    ...extra,
  });
  const product = (id: string, title: string, variants: unknown[]) => ({
    id,
    external_id: `gid://shopify/Product/${id}`,
    title,
    handle: null,
    product_type: null,
    vendor: null,
    status: "active",
    updated_at: null,
    variants,
  });

  it("shows stock and cost with their availability, searches and loads more", async () => {
    const pages: Record<string, unknown> = {
      first: {
        items: [
          product("p1", "Nitrile Gloves", [
            variant(),
            variant({
              id: "v2",
              title: "Large",
              sku: "NG-L",
              cost: {
                availability: "unavailable",
                unit_cost: null,
                source: null,
                effective_from: null,
                reason: "no_cost_from_platform",
              },
            }),
          ]),
          product("p2", "Gift Wrap", [
            variant({
              id: "v3",
              title: "Default Title",
              sku: null,
              inventory: {
                availability: "unavailable",
                tracked: false,
                available: null,
                synced_at: null,
              },
            }),
          ]),
        ],
        next_cursor: "abc",
      },
      second: { items: [product("p3", "Zinc Cream", [])], next_cursor: null },
    };
    const api = baseApi("analyst", {
      [`GET ${STORE_PATH}`]: ok(store()),
      [`GET ${STORE_PATH}/products`]: () => ok(pages.first),
    });
    renderWithProviders(
      inShell(<ProductsPage />, `/orgs/${ORG_ID}/stores/${STORE}/products`, { storeId: STORE }),
      { session: me },
    );
    const table = await screen.findByRole("table");
    expect(within(table).getAllByText(/\$19\.90$/).length).toBeGreaterThan(0);
    expect(within(table).getAllByText("120")).toHaveLength(2);
    expect(within(table).getAllByText(/\$7\.25$/)).toHaveLength(2);
    expect(within(table).getAllByText("Cost when first imported")).toHaveLength(2);
    expect(within(table).getByText("No cost on the platform")).toBeInTheDocument();
    expect(within(table).getByText("Not tracked")).toBeInTheDocument();
    expect(within(table).queryByText(/^0$/)).toBeNull();

    api.set(`GET ${STORE_PATH}/products`, ok(pages.second));
    click(screen.getByRole("button", { name: "Show more products" }));
    expect(await screen.findByText("Zinc Cream")).toBeInTheDocument();
    expect(screen.getByText("No variants")).toBeInTheDocument();

    api.set(`GET ${STORE_PATH}/products`, ok({ items: [], next_cursor: null }));
    fill(screen.getByLabelText("Search by name or SKU"), "nothing");
    click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("No products match.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Eve Zone/ })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/stores/${STORE}`,
    );
  });

  it("shows API errors", async () => {
    baseApi("owner", {
      [`GET ${STORE_PATH}`]: ok(store()),
      [`GET ${STORE_PATH}/products`]: fail(500, "INTERNAL_ERROR"),
    });
    renderWithProviders(
      inShell(<ProductsPage />, `/orgs/${ORG_ID}/stores/${STORE}/products`, { storeId: STORE }),
      { session: me },
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  });
});

describe("WooCommerce stores (2B-08)", () => {
  const woo = (health: Record<string, unknown> | null = null) =>
    store({
      provider: "woocommerce",
      domain: "shop.example.com",
      name: "Eve Zone Woo",
      site_url: "https://shop.example.com",
      platform_version: "10.4.1",
      counted_statuses: ["processing", "on-hold", "completed", "refunded"],
      health: health ?? { code: null, checked_at: "2026-10-14T00:00:00Z" },
    });

  function render(s: unknown) {
    baseApi("manager", {
      [`GET ${STORE_PATH}`]: ok(s),
      [`GET ${STORE_PATH}/metrics/daily`]: ok(metrics()),
    });
    renderWithProviders(
      inShell(<StorePage />, `/orgs/${ORG_ID}/stores/${STORE}`, { storeId: STORE }),
      { session: me },
    );
  }

  it("shows the address, version and which orders are counted; no warning when healthy", async () => {
    render(woo());
    expect(await screen.findByText("https://shop.example.com")).toBeInTheDocument();
    expect(screen.getByText("WooCommerce version")).toBeInTheDocument();
    expect(screen.getByText("10.4.1")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Counted in the figures: processing, on hold, completed and refunded orders\. Orders pending payment, failed, cancelled/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: /needs updating|not set|Cost not available/ }),
    ).toBeNull();
  });

  it.each([
    [
      "cost_of_goods_off",
      "Cost not available — switch on Cost of Goods Sold in WooCommerce",
      /Settings → Advanced → Features/,
    ],
    ["woocommerce_too_old", "WooCommerce needs updating", /version 9\.0 or newer/],
    ["timezone_unknown", "The store's time zone is not set", /choose a city/],
    ["auth_header_stripped", "Your web host blocks the login details", /Authorization header/],
    ["key_rejected", "Needs reconnecting", /no longer accepts/],
    ["retryable", "The daily check could not finish", /try again tomorrow/],
  ])("explains the %s health warning with its fix, never as a code", async (code, title, fix) => {
    render(woo({ code, checked_at: "2026-10-14T00:00:00Z" }));
    const panel = await screen.findByRole("region", { name: title });
    expect(within(panel).getByText(fix)).toBeInTheDocument();
    expect(within(panel).getByText(/^Checked /)).toBeInTheDocument();
    expect(screen.queryByText(code)).toBeNull();
  });

  it("Shopify stores show neither a version nor a counted-status note", async () => {
    render(store());
    expect(await screen.findByText("eve-zone.myshopify.com")).toBeInTheDocument();
    expect(screen.queryByText("WooCommerce version")).toBeNull();
    expect(screen.queryByText(/Counted in the figures/)).toBeNull();
  });

  it("the products page says why costs are missing when Cost of Goods is off", async () => {
    baseApi("viewer", {
      [`GET ${STORE_PATH}`]: ok(woo({ code: "cost_of_goods_off", checked_at: null })),
      [`GET ${STORE_PATH}/products`]: ok({ items: [], next_cursor: null }),
    });
    renderWithProviders(
      inShell(<ProductsPage />, `/orgs/${ORG_ID}/stores/${STORE}/products`, { storeId: STORE }),
      { session: me },
    );
    expect(
      await screen.findByText(/Cost of Goods Sold is switched off in WooCommerce/),
    ).toBeInTheDocument();
  });

  it("explains WooCommerce access problems after import in plain words", async () => {
    render(
      store(
        { provider: "woocommerce", connection_status: "expired" },
        { last_error_code: "key_rejected", last_error_at: "2026-10-14T00:00:00Z" },
      ),
    );
    expect(await screen.findByText(/no longer accepts AdVegaX's access key/)).toBeInTheDocument();
  });
});
