import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { ReportsPage } from "@/features/overview/ReportsPage";
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

function render() {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = `/orgs/${ORG_ID}/reports`;
  return renderWithProviders(
    <OrganizationShell>
      <ReportsPage />
    </OrganizationShell>,
    { session: testUser() },
  );
}

const STORE_A = "5a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
const STORE_B = "6b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e";

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
  formula: `${label}: the formula.`,
  note,
  sources: ["ads"],
});

const PLATFORM_DEFS = [
  def("spend", "Spend", "money"),
  def("clicks", "Clicks", "count"),
  def("impressions", "Impressions", "count"),
  def("conversions", "Conversions", "decimal"),
  def("conversion_value", "Conversion value", "money"),
  def("platform_roas", "Platform ROAS", "multiple"),
  def("cost_per_click", "Cost per click", "money"),
  def("cost_per_conversion", "Cost per conversion", "money"),
];
const GA_DEFS = [
  def("sessions", "Sessions", "count"),
  def("engaged_sessions", "Engaged sessions", "count"),
  def("engagement_rate", "Engagement rate", "ratio"),
  def("key_events", "Key events", "decimal"),
  def("purchases", "Purchases", "count"),
  def("purchase_revenue", "Purchase revenue", "money"),
];

const platformFigures = (spend: string) => ({
  spend: figure(spend),
  clicks: figure("15"),
  impressions: figure("2000"),
  conversions: figure("2.5"),
  conversion_value: figure("80"),
  platform_roas: figure("0.533333"),
  cost_per_click: figure("10.000000"),
  cost_per_conversion: figure(null, "no_conversions"),
});

const channels = (extra: Record<string, unknown> = {}) =>
  emptyOverview({
    definitions: [...PLATFORM_DEFS, ...GA_DEFS],
    ad_spend: figure("204.50"),
    platforms: [
      {
        provider: "google_ads",
        source: "platform_reported",
        ad_accounts: 1,
        figures: platformFigures("150"),
      },
      {
        provider: "meta_ads",
        source: "platform_reported",
        ad_accounts: 2,
        figures: platformFigures("54.50"),
      },
    ],
    analytics_channels: [
      {
        channel: "Paid Search",
        figures: {
          sessions: figure("400"),
          engaged_sessions: figure("20"),
          engagement_rate: figure("0.050000"),
          key_events: figure("2"),
          purchases: figure("2"),
          purchase_revenue: figure("20"),
        },
      },
    ],
    analytics_channels_missing: null,
    ...extra,
  });

const campaign = (name: string, extra: Record<string, unknown> = {}) => ({
  id: `c-${name}`,
  ad_account_id: "a-1",
  provider: "google_ads",
  source: "platform_reported",
  name,
  status: "active",
  budget_period: "daily",
  figures: {
    spend: figure("150"),
    clicks: figure("15"),
    conversions: figure("3"),
    conversion_value: figure("450"),
    platform_roas: figure("3.000000"),
    cost_per_conversion: figure("50.000000"),
    budget_use: figure("0.833333"),
  },
  analytics: {
    sessions: figure("50"),
    purchases: figure("2"),
    purchase_revenue: figure("150.5"),
  },
  analytics_missing: null,
  ...extra,
});

const campaigns = (items: unknown[]) =>
  emptyOverview({
    definitions: [
      ...PLATFORM_DEFS,
      def(
        "budget_use",
        "Budget use",
        "ratio",
        "Uses today's budget for every day, as the platforms do not keep budget history.",
      ),
      ...GA_DEFS.filter((d) => ["sessions", "purchases", "purchase_revenue"].includes(d.key)),
    ],
    sources: [
      { ...storeSource("a-1", "Eve Zone Ads"), kind: "ad_account", provider: "google_ads" },
    ],
    items,
  });

const productDefs = [
  def("units", "Units sold", "count"),
  def("net_sales", "Net sales", "money"),
  def("product_cost", "Product cost", "money"),
  def("gross_profit", "Gross profit", "money"),
  def("gross_margin", "Gross margin", "ratio"),
];

const product = (title: string | null, store: string, cost: boolean) => ({
  product_id: title ? `p-${title}` : null,
  store_id: store,
  title,
  figures: {
    units: figure("3"),
    net_sales: figure("75"),
    product_cost: cost ? figure("30") : figure(null, "missing_product_costs"),
    gross_profit: cost ? figure("45") : figure(null, "missing_product_costs"),
    gross_margin: cost ? figure("0.600000") : figure(null, "missing_product_costs"),
  },
});

const storeSource = (id: string, name: string) => ({
  kind: "store",
  id,
  provider: "shopify",
  name,
  currency: "AUD",
  timezone: "Australia/Sydney",
  synced_from: "2025-10-05",
  updated_at: "2026-10-14T03:00:00Z",
});

const routes = (extra: Record<string, Response> = {}) => ({
  [`GET ${ORG_PATH}`]: ok(testOrg()),
  ...emptyOrganizationData(),
  [`GET ${ORG_PATH}/analytics/channels`]: ok(channels()),
  [`GET ${ORG_PATH}/analytics/campaigns`]: ok(
    campaigns([
      campaign("Spring Sale"),
      campaign("Brand", {
        provider: "meta_ads",
        status: "paused",
        figures: {
          ...campaign("x").figures,
          budget_use: figure(null, "not_a_daily_budget", "unsupported"),
        },
        analytics: {
          sessions: figure(null, "no_match"),
          purchases: figure(null, "no_match"),
          purchase_revenue: figure(null, "no_match"),
        },
      }),
      campaign("Old", {
        analytics: null,
        analytics_missing: figure(null, "no_analytics_property"),
      }),
    ]),
  ),
  [`GET ${ORG_PATH}/analytics/products`]: ok(
    emptyOverview({
      definitions: productDefs,
      sources: [storeSource(STORE_A, "Eve Zone"), storeSource(STORE_B, "Mediflex")],
      items: [product("Nitrile gloves", STORE_A, true), product(null, STORE_B, false)],
      items_missing: null,
      other_currency_lines: 2,
    }),
  ),
  ...extra,
});

describe("Reports", () => {
  it("shows each platform's own figures and Google Analytics' channels", async () => {
    const api = mockApi(routes());
    render();
    expect(await screen.findByRole("heading", { level: 1, name: "Reports" })).toBeVisible();
    const platforms = await screen.findByRole("table", { name: /Reported by each platform/ });
    const rows = within(platforms).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Google Ads");
    expect(rows[1]).toHaveTextContent("1 ad account · platform reported");
    expect(rows[1]).toHaveTextContent("A$150.00");
    expect(rows[1]).toHaveTextContent("0.53×");
    expect(rows[1]).toHaveTextContent("No conversions");
    expect(rows[2]).toHaveTextContent("2 ad accounts");
    expect(screen.getByText("A$204.50")).toBeVisible();
    const ga = screen.getByRole("table", { name: /default channel groups/ });
    expect(within(ga).getAllByRole("row")[1]).toHaveTextContent("Paid Search400205.0%22A$20.00");
    // "How these figures are calculated", from the registry.
    expect(screen.getAllByText("How these figures are calculated")).toHaveLength(2);
    expect(screen.getByText("Platform ROAS: the formula.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Where the numbers come from" })).toBeVisible();
    // Only the chosen report is read.
    const paths = api.apiCalls().map((c) => c.path);
    expect(paths.some((p) => p.endsWith("/analytics/channels"))).toBe(true);
    expect(paths.some((p) => p.endsWith("/analytics/campaigns"))).toBe(false);
  });

  it("says why there are no platforms or channels", async () => {
    mockApi(
      routes({
        [`GET ${ORG_PATH}/analytics/channels`]: ok(
          channels({
            ad_spend: figure(null, "no_ad_account"),
            platforms: [],
            analytics_channels: [],
            analytics_channels_missing: figure(null, "no_analytics_property"),
          }),
        ),
      }),
    );
    render();
    expect(await screen.findByText("No ad account connected.")).toBeVisible();
    expect(screen.getByText("No Google Analytics property.")).toBeVisible();
  });

  it("shows campaigns with budget use and the Google Analytics match", async () => {
    const api = mockApi(routes());
    render();
    fill(await screen.findByLabelText("Report"), "campaigns");
    const table = await screen.findByRole("table", { name: /campaign of the same name/ });
    const rows = within(table).getAllByRole("row");
    expect(rows[0]).toHaveTextContent("Sessions (Google Analytics)");
    expect(rows[1]).toHaveTextContent("Spring Sale");
    expect(rows[1]).toHaveTextContent("83.3%");
    expect(rows[1]).toHaveTextContent("A$150.50");
    expect(rows[2]).toHaveTextContent("Meta · Eve Zone Ads · Paused");
    expect(rows[2]).toHaveTextContent("Not a daily budget");
    expect(rows[2]).toHaveTextContent("No matching Google Analytics campaign");
    expect(
      within(rows[3] as HTMLElement).getByText("No Google Analytics property"),
    ).toHaveAttribute("colspan", "3");
    expect(screen.getByText(/as the platforms do not keep budget history/)).toBeInTheDocument();
    expect(api.apiCalls().some((c) => c.path.endsWith("/analytics/campaigns"))).toBe(true);
  });

  it("shows products, their store, and lines left out", async () => {
    mockApi(routes());
    render();
    fill(await screen.findByLabelText("Report"), "products");
    const table = await screen.findByRole("table", { name: /From your store platform/ });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Nitrile gloves");
    expect(rows[1]).toHaveTextContent("Eve Zone");
    expect(rows[1]).toHaveTextContent("60.0%");
    expect(rows[2]).toHaveTextContent("Items not matched to a product");
    expect(rows[2]).toHaveTextContent("Some products have no cost");
    expect(screen.getByText(/2 sold items are/)).toBeVisible();
  });

  it("says why there are no products, and shows errors", async () => {
    mockApi(
      routes({
        [`GET ${ORG_PATH}/analytics/products`]: ok(
          emptyOverview({
            definitions: productDefs,
            items: [],
            items_missing: figure(null, "no_store"),
            other_currency_lines: 0,
          }),
        ),
        [`GET ${ORG_PATH}/analytics/campaigns`]: fail(500, "INTERNAL_ERROR"),
      }),
    );
    render();
    fill(await screen.findByLabelText("Report"), "products");
    expect(await screen.findByText("No store connected.")).toBeVisible();
    fill(screen.getByLabelText("Report"), "campaigns");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
