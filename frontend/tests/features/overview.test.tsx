import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationOverview } from "@/features/organizations/OrganizationOverview";
import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { addDays, formatDay } from "@/features/stores/dates";
import { clearCsrfToken } from "@/lib/api/csrf";

import { fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import {
  ORG_ID,
  ORG_PATH,
  emptyOrganizationData,
  emptyOverview,
  testOrg,
} from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

function inShell(ui: React.ReactElement, path = `/orgs/${ORG_ID}`) {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = path;
  return <OrganizationShell>{ui}</OrganizationShell>;
}

const STORE_A = "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const STORE_B = "6b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e";
const ACCOUNT = "7c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f";
const PROPERTY = "8d4e5f6a-7b8c-4d9e-8f0a-2b3c4d5e6f7a";

const figure = (
  value: string | null,
  reason: string | null = null,
  availability = "available",
) => ({
  value,
  availability: value === null && availability === "available" ? "unavailable" : availability,
  reason,
});

const def = (key: string, label: string, unit: string, note: string | null = null) => ({
  key,
  label,
  unit,
  formula: `${label} formula`,
  note,
  sources: ["stores"],
});

const DEFINITIONS = [
  def("net_sales", "Net sales", "money"),
  def("orders", "Orders", "count"),
  def("product_cost", "Product cost", "money"),
  def("gross_profit", "Gross profit", "money"),
  def("gross_margin", "Gross margin", "ratio"),
  def("ad_spend", "Ad spend", "money"),
  def(
    "profit_after_ad_spend",
    "Profit after ad spend",
    "money",
    "Before shipping costs and payment fees, which the store platforms do not provide.",
  ),
  def("blended_roas", "Blended ROAS", "multiple"),
  def("cost_per_order", "Cost per order", "money"),
  def("ad_spend_share", "Ad spend share of sales", "ratio"),
  def("shipping_cost", "Shipping cost", "money"),
  def("payment_fees", "Payment fees", "money"),
  def("contribution_profit", "Contribution profit", "money"),
  def("customer_acquisition_cost", "Customer acquisition cost", "money"),
  def("sessions", "Sessions", "count"),
  def("analytics_purchases", "Purchases (Google Analytics)", "count"),
  def("analytics_revenue", "Purchase revenue (Google Analytics)", "money"),
  def("store_conversion_rate", "Store conversion rate", "ratio"),
];

const TOTALS = {
  net_sales: figure("1500.50"),
  orders: figure("15"),
  product_cost: figure("600.20"),
  gross_profit: figure("900.30"),
  gross_margin: figure("0.600000"),
  ad_spend: figure("204.50"),
  profit_after_ad_spend: figure("695.80"),
  blended_roas: figure("7.337408"),
  cost_per_order: figure("13.633333"),
  ad_spend_share: figure("0.136288"),
  shipping_cost: figure(null, "not_provided_by_platform", "unsupported"),
  payment_fees: figure(null, "not_provided_by_platform", "unsupported"),
  contribution_profit: figure(null, "costs_not_entered", "unsupported"),
  customer_acquisition_cost: figure(null, "customer_key_not_collected"),
  sessions: figure("600"),
  analytics_purchases: figure("12"),
  analytics_revenue: figure("1400.000000"),
  store_conversion_rate: figure("0.025000"),
};

const source = (
  kind: string,
  id: string,
  provider: string,
  name: string | null,
  currency = "AUD",
) => ({
  kind,
  id,
  provider,
  name,
  currency,
  timezone: "Australia/Sydney",
  synced_from: "2025-10-05",
  updated_at: "2026-10-14T03:00:00Z",
});

const golden = (overrides: Record<string, unknown> = {}) =>
  emptyOverview({
    from_day: "2026-10-05",
    to_day: "2026-10-07",
    totals: TOTALS,
    days: [
      { day: "2026-10-05", figures: { ...TOTALS, net_sales: figure("1000.00") } },
      { day: "2026-10-06", figures: { ...TOTALS, net_sales: figure("500.50") } },
      {
        day: "2026-10-07",
        figures: { ...TOTALS, net_sales: figure(null, "not_synchronized", "not_synchronized") },
      },
    ],
    sources: [
      source("store", STORE_A, "shopify", "Eve Zone"),
      source("ad_account", ACCOUNT, "meta_ads", "Eve Zone Meta", "USD"),
      source("analytics_property", PROPERTY, "google_analytics", null),
    ],
    conversions: [
      {
        currency: "USD",
        rate_sources: ["ecb"],
        first_rate_date: "2026-10-05",
        last_rate_date: "2026-10-06",
        days_without_rate: 0,
      },
    ],
    definitions: DEFINITIONS,
    ...overrides,
  });

const store = (id: string, name: string) => ({
  id,
  resource_id: `r-${id}`,
  provider: "shopify",
  domain: `${name.toLowerCase().replaceAll(" ", "-")}.myshopify.com`,
  name,
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  status: "active",
  linked: true,
  connection_status: "active",
  history_from: null,
  first_import_completed_at: null,
  sync: { running: false },
  created_at: "2026-10-01T00:00:00Z",
});

describe("Overview", () => {
  it("shows the period's figures, days, sources and conversions from the API", async () => {
    const api = mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      ...emptyOrganizationData(),
      [`GET ${ORG_PATH}/analytics/overview`]: ok(golden()),
    });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    const sales = await screen.findByRole("list", { name: "Sales and profit" });
    expect(within(sales).getByText("Net sales").nextSibling).toHaveTextContent("A$1,500.50");
    const ads = screen.getByRole("list", { name: "Advertising" });
    expect(within(ads).getByText("Blended ROAS").nextSibling).toHaveTextContent("7.34×");
    expect(within(ads).getByText("Cost per order").nextSibling).toHaveTextContent("A$13.63");
    expect(within(ads).getByText("Ad spend share of sales").nextSibling).toHaveTextContent("13.6%");
    expect(within(ads).getByText(/^Before shipping costs and payment fees/)).toBeInTheDocument();
    const missing = screen.getByRole("list", { name: "Not included yet" });
    expect(within(missing).getByText("Shipping cost").nextSibling).toHaveTextContent(
      "Not provided by the platform",
    );
    expect(within(missing).getByText("Contribution profit").nextSibling).toHaveTextContent(
      "Shipping costs and fees not entered",
    );
    // Days newest first; a day not read says so, never 0.
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows[1]).toHaveTextContent(formatDay("2026-10-07"));
    expect(rows[1]).toHaveTextContent("Not synced yet");
    expect(rows[3]).toHaveTextContent("A$1,000.00");
    // Where the numbers come from.
    expect(screen.getByText("Eve Zone Meta")).toBeInTheDocument();
    expect(screen.getByText("Google Analytics google analytics property")).toBeInTheDocument();
    expect(
      screen.getByText(/Amounts in USD are converted to AUD with European Central Bank rates/),
    ).toBeInTheDocument();
    expect(screen.getByText(/definitions “analytics-v1”/)).toBeInTheDocument();
    // A 30-day period ending today in the reporting time zone; no store chosen.
    const call = api.apiCalls().find((c) => c.path.endsWith("/analytics/overview"));
    const from = call?.query.get("from") ?? "";
    expect(addDays(from, 29)).toBe(call?.query.get("to"));
    expect(call?.query.has("store_id")).toBe(false);
    // One store: no store choice.
    expect(screen.queryByLabelText("Store")).not.toBeInTheDocument();
  });

  it("explains missing rates and differing time zones", async () => {
    mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      ...emptyOrganizationData(),
      [`GET ${ORG_PATH}/analytics/overview`]: ok(
        golden({
          notes: ["time_zones_differ"],
          conversions: [
            {
              currency: "USD",
              rate_sources: ["ecb", "nrb"],
              first_rate_date: "2026-10-05",
              last_rate_date: "2026-10-05",
              days_without_rate: 3,
            },
          ],
        }),
      ),
    });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    expect(
      await screen.findByText(
        new RegExp(
          `European Central Bank and Nepal Rastra Bank rates published ${formatDay("2026-10-05")},`,
        ),
      ),
    ).toHaveTextContent("3 days have no exchange rate");
    expect(screen.getByText(/different time zone from your reporting time zone/)).toBeVisible();
  });

  it("changes the period and the store", async () => {
    const api = mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      ...emptyOrganizationData(),
      [`GET ${ORG_PATH}/stores`]: ok([store(STORE_A, "Eve Zone"), store(STORE_B, "Mediflex")]),
      [`GET ${ORG_PATH}/analytics/overview`]: ok(golden()),
    });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    fill(await screen.findByLabelText("Store"), STORE_B);
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.query.get("store_id") === STORE_B)).toBe(true),
    );
    fill(screen.getByLabelText("Period"), "7");
    await waitFor(() => {
      const last = api
        .apiCalls()
        .filter((c) => c.path.endsWith("/analytics/overview"))
        .at(-1);
      expect(addDays(last?.query.get("from") ?? "", 6)).toBe(last?.query.get("to"));
      expect(last?.query.get("store_id")).toBe(STORE_B);
    });
  });

  it("says what to connect when nothing is connected, and shows errors", async () => {
    mockApi({ [`GET ${ORG_PATH}`]: ok(testOrg()), ...emptyOrganizationData() });
    const { unmount } = renderWithProviders(inShell(<OrganizationOverview />), {
      session: testUser(),
    });
    expect(await screen.findByRole("link", { name: "See connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
    unmount();
    mockApi({
      [`GET ${ORG_PATH}`]: ok(testOrg()),
      ...emptyOrganizationData(),
      [`GET ${ORG_PATH}/analytics/overview`]: fail(500, "INTERNAL_ERROR"),
    });
    renderWithProviders(inShell(<OrganizationOverview />), { session: testUser() });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

const adAccount = (storeId: string | null) => ({
  id: ACCOUNT,
  provider: "google_ads",
  external_account_id: "123-456-7890",
  name: "Eve Zone Ads",
  store_id: storeId,
  sync: { running: false },
});
const property = (storeId: string | null) => ({
  id: PROPERTY,
  provider: "google_analytics",
  external_property_id: "111",
  name: null,
  store_id: storeId,
  sync: { running: false },
});

describe("Settings: stores for ad accounts and properties", () => {
  const routes = (role = "owner") => ({
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    [`GET ${ORG_PATH}/stores`]: ok([store(STORE_A, "Eve Zone"), store(STORE_B, "Mediflex")]),
    [`GET ${ORG_PATH}/ad-accounts`]: ok([adAccount(null)]),
    [`GET ${ORG_PATH}/analytics-properties`]: ok([property(STORE_A)]),
  });

  it("lets an owner choose each one's store, saved straight away", async () => {
    const api = mockApi({
      ...routes(),
      [`PUT ${ORG_PATH}/ad-accounts/${ACCOUNT}/store`]: ok(adAccount(STORE_B)),
      [`PUT ${ORG_PATH}/analytics-properties/${PROPERTY}/store`]: ok(property(null)),
    });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    const ads = await screen.findByLabelText("Store for Eve Zone Ads (Google Ads)");
    expect(ads).toHaveValue("");
    const ga = screen.getByLabelText("Store for 111 (Google Analytics)");
    expect(ga).toHaveValue(STORE_A);
    fill(ads, STORE_B);
    expect(
      await screen.findByText("Eve Zone Ads (Google Ads) now counts for Mediflex."),
    ).toBeVisible();
    fill(ga, "");
    expect(
      await screen.findByText("111 (Google Analytics) now counts for all stores."),
    ).toBeVisible();
    const puts = api.apiCalls().filter((c) => c.method === "PUT");
    expect(puts.map((c) => c.body)).toEqual([{ store_id: STORE_B }, { store_id: null }]);
    expect(puts.every((c) => c.csrf === "csrf-test")).toBe(true);
  });

  it("explains a refused change", async () => {
    mockApi({
      ...routes(),
      [`PUT ${ORG_PATH}/ad-accounts/${ACCOUNT}/store`]: fail(403, "FORBIDDEN"),
    });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    fill(await screen.findByLabelText("Store for Eve Zone Ads (Google Ads)"), STORE_A);
    expect(await screen.findByText(/You do not have permission/)).toBeVisible();
  });

  it("is read-only below admin", async () => {
    mockApi(routes("manager"));
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    expect(await screen.findByText("Eve Zone Ads (Google Ads)")).toBeInTheDocument();
    expect(screen.getByText("111 (Google Analytics)").nextSibling).toHaveTextContent("Eve Zone");
    expect(screen.queryByLabelText(/^Store for/)).not.toBeInTheDocument();
  });

  it("has nothing to set with one store", async () => {
    mockApi({ ...routes(), [`GET ${ORG_PATH}/stores`]: ok([store(STORE_A, "Eve Zone")]) });
    renderWithProviders(inShell(<OrganizationSettings />), { session: testUser() });
    expect(await screen.findByText(/You have one store/)).toBeVisible();
  });
});
