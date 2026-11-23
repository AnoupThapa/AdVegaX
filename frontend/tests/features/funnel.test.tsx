import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FunnelPage } from "@/features/funnel/FunnelPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { formatDay } from "@/features/stores/dates";
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
  navigation.pathname = `/orgs/${ORG_ID}/funnel`;
  return renderWithProviders(
    <OrganizationShell>
      <FunnelPage />
    </OrganizationShell>,
    { session: testUser() },
  );
}

const FUNNEL = `${ORG_PATH}/analytics/funnel`;

const figure = (
  value: string | null,
  reason: string | null = null,
  availability = "available",
) => ({
  value,
  availability: value === null && availability === "available" ? "unavailable" : availability,
  reason,
});

const def = (key: string, label: string, source: string) => ({
  key,
  label,
  unit: "count",
  formula: `${label}: how it is counted.`,
  note: null,
  sources: [source],
});

const DEFINITIONS = [
  def("impressions", "Impressions", "ads"),
  def("clicks", "Clicks", "ads"),
  def("landing_page_views", "Landing page views", "google_analytics"),
  def("product_views", "Product views", "google_analytics"),
  def("adds_to_cart", "Adds to cart", "google_analytics"),
  def("checkouts", "Checkouts started", "google_analytics"),
  def("purchases", "Purchases (store orders)", "stores"),
  def("analytics_purchases", "Purchases (Google Analytics)", "google_analytics"),
];
const PLATFORM_DEFINITIONS = [
  def("impressions", "Impressions", "platform"),
  def("clicks", "Clicks", "platform"),
  def("landing_page_views", "Landing page views", "platform"),
  def("product_views", "Content views", "platform"),
  def("adds_to_cart", "Adds to cart", "platform"),
  def("checkouts", "Checkouts started", "platform"),
  def("purchases", "Purchases", "platform"),
];

const step = (from: string, to: string, rate: string | null, kind = "same_source") => ({
  from_stage: from,
  to_stage: to,
  kind,
  rate: kind === "different_sources" ? null : figure(rate),
});

const STAGES = {
  impressions: figure("4800"),
  clicks: figure("140"),
  landing_page_views: figure("500"),
  product_views: figure("200"),
  adds_to_cart: figure("50"),
  checkouts: figure("20"),
  purchases: figure("15"),
  analytics_purchases: figure("10"),
};

const funnel = (extra: Record<string, unknown> = {}) =>
  emptyOverview({
    definition_version: "funnel-v1",
    definitions: DEFINITIONS,
    platform_definitions: PLATFORM_DEFINITIONS,
    stages: STAGES,
    steps: [
      step("impressions", "clicks", "0.029167"),
      step("clicks", "landing_page_views", null, "different_sources"),
      step("landing_page_views", "product_views", "0.400000"),
      step("product_views", "adds_to_cart", "0.250000"),
      step("adds_to_cart", "checkouts", "0.400000"),
      step("checkouts", "analytics_purchases", "0.500000"),
      step("landing_page_views", "purchases", "0.030000", "store_conversion"),
    ],
    platforms: [
      {
        provider: "google_ads",
        source: "platform_reported",
        ad_accounts: 1,
        stages: {
          impressions: figure("1800"),
          clicks: figure("80"),
          landing_page_views: figure(null, "not_provided_by_platform", "unsupported"),
          product_views: figure(null, "not_provided_by_platform", "unsupported"),
          adds_to_cart: figure(null, "not_provided_by_platform", "unsupported"),
          checkouts: figure(null, "not_provided_by_platform", "unsupported"),
          purchases: figure("3"),
        },
        steps: [step("impressions", "clicks", "0.044444"), step("clicks", "purchases", "0.037500")],
      },
      {
        provider: "meta_ads",
        source: "platform_reported",
        ad_accounts: 2,
        stages: {
          impressions: figure("3000"),
          clicks: figure("60"),
          landing_page_views: figure("45"),
          product_views: figure("30"),
          adds_to_cart: figure("12"),
          checkouts: figure("6"),
          purchases: figure("4"),
        },
        steps: [step("impressions", "clicks", "0.020000")],
      },
    ],
    channels: [
      {
        channel: "Organic Search",
        stages: {
          landing_page_views: figure("280"),
          product_views: figure("90"),
          adds_to_cart: figure("28"),
          checkouts: figure("9"),
          analytics_purchases: figure("4"),
        },
        steps: [step("landing_page_views", "product_views", "0.321429")],
      },
    ],
    channels_missing: null,
    findings: [
      {
        view: "whole",
        subject: null,
        from_stage: "product_views",
        to_stage: "adds_to_cart",
        rate: "0.150000",
        previous_rate: "0.250000",
        baseline_rate: "0.240000",
        events_before: "280",
        change: "-0.4000",
      },
      {
        view: "platform",
        subject: "meta_ads",
        from_stage: "impressions",
        to_stage: "clicks",
        rate: "0.010000",
        previous_rate: "0.020000",
        baseline_rate: "0.020000",
        events_before: "3000",
        change: "-0.5000",
      },
    ],
    rules: {
      drop_share: "0.25",
      min_events: 200,
      baseline_days: 90,
      previous_from: "2026-09-15",
      previous_to: "2026-10-14",
    },
    ...extra,
  });

const routes = (extra: Record<string, Response> = {}) => ({
  [`GET ${ORG_PATH}`]: ok(testOrg()),
  ...emptyOrganizationData(),
  [`GET ${FUNNEL}`]: ok(funnel()),
  ...extra,
});

describe("Funnel", () => {
  it("shows every stage with its source, the steps and the findings", async () => {
    const api = mockApi(routes());
    render();
    const stages = await screen.findByRole("list", { name: "Stages" });
    const items = within(stages).getAllByRole("listitem");
    expect(items).toHaveLength(8);
    expect(items[0]).toHaveTextContent("Impressions 4,800");
    expect(items[0]).toHaveTextContent("Google Ads and Meta");
    expect(items[2]).toHaveTextContent("Google Analytics");
    expect(items[6]).toHaveTextContent("Your stores");
    expect(within(stages).getByRole("meter", { name: "Clicks: 140" })).toBeInTheDocument();
    expect(within(stages).getAllByText("How is this calculated?")).toHaveLength(8);
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(steps).toHaveTextContent("Product views → Adds to cart: 25.0%");
    expect(steps).toHaveTextContent("Clicks → Landing page views: Different sources — no rate");
    expect(steps).toHaveTextContent("Store conversion rate (store orders per visit): 3.0%");
    expect(
      screen.getByText(
        `Adds to cart fell from 25.0% to 15.0% of product views, compared with ${formatDay("2026-09-15")} to ${formatDay("2026-10-14")}. It is also below its usual 24.0%.`,
      ),
    ).toBeVisible();
    expect(screen.getByText(/^Clicks \(Meta\) fell from 2.0% to 1.0%/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Where the numbers come from" })).toBeVisible();
    expect(api.apiCalls().filter((c) => c.path.startsWith(FUNNEL))).toHaveLength(1);
  });

  it("explains the rules when nothing dropped", async () => {
    mockApi(routes({ [`GET ${FUNNEL}`]: ok(funnel({ findings: [] })) }));
    render();
    expect(
      await screen.findByText(/at least 25.0% lower than in the previous period/),
    ).toHaveTextContent("own 90-day average, with at least 200 events");
  });

  it("shows each platform's own funnel, and what it does not provide", async () => {
    mockApi(routes());
    render();
    fill(await screen.findByLabelText("Show"), "platforms");
    const google = await screen.findByRole("list", { name: "Google Ads stages" });
    expect(within(google).getAllByRole("listitem")[2]).toHaveTextContent(
      "Not provided by the platform",
    );
    expect(within(google).getAllByRole("listitem")[0]).toHaveTextContent("Reported by Google Ads");
    const meta = screen.getByRole("list", { name: "Meta stages" });
    expect(within(meta).getAllByRole("listitem")[3]).toHaveTextContent("Content views 30");
    expect(screen.getByText(/for 2 ad accounts, with its own attribution/)).toBeVisible();
  });

  it("shows the Google Analytics channels as a table", async () => {
    mockApi(routes());
    render();
    fill(await screen.findByLabelText("Show"), "channels");
    const table = await screen.findByRole("table", { name: /Each channel's own funnel/ });
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Organic Search28090289432.1%");
  });

  it("shows campaigns with their Google Analytics part, other traffic and the website", async () => {
    mockApi(
      routes({
        [`GET ${FUNNEL}/campaigns`]: ok(
          emptyOverview({
            definitions: DEFINITIONS,
            platform_definitions: PLATFORM_DEFINITIONS,
            items: [
              {
                id: "c-1",
                ad_account_id: "a-1",
                provider: "meta_ads",
                source: "platform_reported",
                name: "Gloves",
                status: "active",
                stages: {
                  impressions: figure("900"),
                  clicks: figure("20"),
                  purchases: figure("2"),
                },
                steps: [],
                analytics: {
                  landing_page_views: figure("20"),
                  adds_to_cart: figure("4"),
                  analytics_purchases: figure("1"),
                },
                analytics_steps: [],
                shared_match: true,
              },
              {
                id: "c-2",
                ad_account_id: "a-2",
                provider: "google_ads",
                source: "platform_reported",
                name: "Brand",
                status: "paused",
                stages: {
                  impressions: figure("500"),
                  clicks: figure("25"),
                  purchases: figure("1"),
                },
                steps: [],
                analytics: {
                  landing_page_views: figure(null, "no_match"),
                  adds_to_cart: figure(null, "no_match"),
                  analytics_purchases: figure(null, "no_match"),
                },
                analytics_steps: [],
                shared_match: false,
              },
            ],
            other_traffic: {
              landing_page_views: figure("100"),
              adds_to_cart: figure("10"),
              analytics_purchases: figure("2"),
            },
            other_traffic_steps: [],
            website: {
              landing_page_views: figure("120"),
              adds_to_cart: figure("14"),
              analytics_purchases: figure("3"),
            },
            analytics_missing: null,
          }),
        ),
      }),
    );
    render();
    fill(await screen.findByLabelText("Show"), "campaigns");
    const table = await screen.findByRole("table", { name: /platform's own/ });
    const rows = within(table).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Gloves");
    expect(rows[1]).toHaveTextContent("Meta · Active · shares its Google Analytics match");
    expect(rows[1]).toHaveTextContent("9002022041");
    expect(rows[2]).toHaveTextContent("No matching Google Analytics campaign");
    expect(rows[3]).toHaveTextContent("Other traffic");
    expect(rows[3]).toHaveTextContent("100102");
    expect(rows[4]).toHaveTextContent("Website");
    expect(rows[4]).toHaveTextContent("120143");
  });

  it("shows landing pages, or why there are none", async () => {
    mockApi(
      routes({
        [`GET ${FUNNEL}/landing-pages`]: ok(
          emptyOverview({
            definitions: DEFINITIONS,
            items: [
              {
                landing_page: "/products/gloves",
                stages: {
                  landing_page_views: figure("100"),
                  product_views: figure("80"),
                  adds_to_cart: figure("30"),
                  checkouts: figure("12"),
                  analytics_purchases: figure("6"),
                },
                steps: [step("landing_page_views", "product_views", "0.800000")],
              },
            ],
            item_count: 1,
            items_missing: null,
          }),
        ),
      }),
    );
    render();
    fill(await screen.findByLabelText("Show"), "landing-pages");
    const table = await screen.findByRole("table", { name: /landing page's own funnel/ });
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("/products/gloves1008030126");
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("80.0%");
  });

  it("says why there are no landing pages yet, and shows errors", async () => {
    mockApi(
      routes({
        [`GET ${FUNNEL}/landing-pages`]: ok(
          emptyOverview({
            definitions: DEFINITIONS,
            items: [],
            item_count: 0,
            items_missing: figure(null, "not_synchronized", "not_synchronized"),
          }),
        ),
        [`GET ${FUNNEL}/campaigns`]: fail(500, "INTERNAL_ERROR"),
      }),
    );
    render();
    fill(await screen.findByLabelText("Show"), "landing-pages");
    expect(await screen.findByText("Not synced yet.")).toBeVisible();
    fill(screen.getByLabelText("Show"), "campaigns");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  });
});
