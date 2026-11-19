import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HeroFlow } from "@/features/home/HeroFlow";
import { Dashboard, TrendChart } from "@/features/overview/Dashboard";

import { mockApi, ok } from "../support/mock-api";
import { ORG_PATH, emptyOverview, testOrg } from "../support/organizations";
import { renderWithProviders } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));
afterEach(() => vi.unstubAllGlobals());

const fig = (value: string | null) => ({
  value,
  availability: value === null ? "unavailable" : "available",
  reason: value === null ? "not_connected" : null,
});
const def = (key: string, label: string, unit: string) => ({
  key,
  label,
  unit,
  formula: "",
  note: null,
  sources: [],
});
const DEFS = [
  def("net_sales", "Net sales", "money"),
  def("profit_after_ad_spend", "Profit after ad spend", "money"),
  def("ad_spend", "Ad spend", "money"),
  def("spend", "Spend", "money"),
  def("conversion_value", "Conversion value", "money"),
  def("platform_roas", "Platform ROAS", "ratio"),
  def("impressions", "Impressions", "count"),
  def("clicks", "Clicks", "count"),
  def("purchases", "Purchases", "count"),
];
const CURRENCY = { currency: "AUD", minorUnits: 2 };
const day = (d: string, sales: string | null, profit: string | null, spend: string | null) => ({
  day: d,
  figures: { net_sales: fig(sales), profit_after_ad_spend: fig(profit), ad_spend: fig(spend) },
});
const overview = (days: unknown[]) => emptyOverview({ definitions: DEFS, days });
const controls = { from: "2026-10-01", to: "2026-10-03", storeId: null };

describe("TrendChart", () => {
  it("says so when there are no daily figures", () => {
    render(<TrendChart data={overview([]) as never} currency={CURRENCY} />);
    expect(screen.getByText(/No daily figures for this period yet/)).toBeInTheDocument();
  });

  it("reads each day by pointer and keyboard, with a gap where a figure is missing", () => {
    const days = [
      day("2026-10-01", "100.00", "-20.00", "30.00"),
      day("2026-10-02", null, null, null),
      day("2026-10-03", "300.00", "120.00", "50.00"),
    ];
    const { container } = render(<TrendChart data={overview(days) as never} currency={CURRENCY} />);
    const readout = container.querySelector("[aria-live]") as HTMLElement;
    // The newest day is shown first.
    expect(within(readout).getByText("A$300.00")).toBeInTheDocument();
    // Profit dips below zero, so the axis has a negative bottom and never reads "-A$0".
    expect(container.textContent).not.toMatch(/-A\$0(?!\.)/);
    const chart = screen.getByRole("group", { name: /Chart by day/ });
    fireEvent.keyDown(chart, { key: "Home" });
    expect(within(readout).getByText("A$100.00")).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(within(readout).getAllByText(/Not available|—/).length).toBeGreaterThan(0);
    fireEvent.keyDown(chart, { key: "End" });
    expect(within(readout).getByText("A$300.00")).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    fireEvent.keyDown(chart, { key: "x" }); // ignored
    chart.getBoundingClientRect = () => ({ left: 0, width: 300 }) as DOMRect;
    fireEvent.pointerMove(chart, { clientX: 10 });
    expect(within(readout).getByText("A$100.00")).toBeInTheDocument();
    fireEvent.pointerLeave(chart);
    expect(within(readout).getByText("A$300.00")).toBeInTheDocument();
    // Two runs of the sales line (split by the missing day) and bars for the days with spend.
    expect(container.querySelectorAll("rect")).toHaveLength(2);
  });
});

const CHANNELS = {
  definitions: DEFS,
  reporting_currency: "AUD",
  currency_minor_units: 2,
  ad_spend: fig("80.00"),
  platforms: [
    {
      provider: "meta_ads",
      figures: { spend: fig("30.00"), conversion_value: fig("90.00"), platform_roas: fig("3") },
    },
    {
      provider: "google_ads",
      figures: { spend: fig("50.00"), conversion_value: fig(null), platform_roas: fig(null) },
    },
  ],
  analytics_channels: [
    { channel: "Direct", figures: { sessions: fig("20") } },
    { channel: "Organic Search", figures: { sessions: fig("70") } },
    { channel: "Email", figures: { sessions: fig("0") } },
  ],
  analytics_channels_missing: null,
};

const FUNNEL = {
  definitions: DEFS,
  reporting_currency: "AUD",
  currency_minor_units: 2,
  stages: { impressions: fig("1000"), clicks: fig("40"), purchases: fig("2") },
  steps: [
    { from_stage: "impressions", to_stage: "clicks", rate: fig("0.04") },
    { from_stage: "clicks", to_stage: "purchases", rate: fig("0.05") },
  ],
  findings: [{ to_stage: "purchases", view: "whole" }],
};

const campaign = (id: string, name: string, spend: string, status = "enabled") => ({
  id,
  name,
  provider: "google_ads",
  status,
  figures: { spend: fig(spend), conversion_value: fig("10.00"), platform_roas: fig("2") },
});

function routes(over: Record<string, unknown> = {}) {
  const base: Record<string, unknown> = {
    channels: CHANNELS,
    funnel: FUNNEL,
    campaigns: {
      definitions: DEFS,
      reporting_currency: "AUD",
      currency_minor_units: 2,
      items: [
        campaign("c1", "Small", "5.00", "paused"),
        campaign("c2", "Big", "50.00"),
        campaign("c3", "Nothing spent", "0.00"),
      ],
    },
    ...over,
  };
  return mockApi({
    [`GET ${ORG_PATH}/analytics/channels`]: ok(base.channels),
    [`GET ${ORG_PATH}/analytics/funnel`]: ok(base.funnel),
    [`GET ${ORG_PATH}/analytics/campaigns`]: ok(base.campaigns),
  });
}

describe("Dashboard", () => {
  it("shows where the money went, the funnel and the campaigns that spent most", async () => {
    routes();
    renderWithProviders(
      <Dashboard
        org={testOrg()}
        data={overview([]) as never}
        currency={CURRENCY}
        controls={controls}
      />,
    );
    const spend = await screen.findByRole("list", { name: "Ad spend by platform" });
    const names = within(spend)
      .getAllByRole("listitem")
      .map((li) => li.textContent);
    expect(names[0]).toMatch(/^Google Ads/); // largest first
    const visits = screen.getByRole("list", { name: "Visits by channel" });
    expect(within(visits).getAllByRole("listitem")).toHaveLength(2); // no zero rows
    expect(await screen.findByText("Below usual")).toBeInTheDocument();
    expect(screen.getByText(/1 step is well below usual/)).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Campaigns that spent most" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("link", { name: "Big" })).toHaveAttribute(
      "href",
      `/orgs/${testOrg().id}/advertising/campaigns/c2`,
    );
  });

  it("explains empty sections", async () => {
    routes({
      channels: {
        ...CHANNELS,
        platforms: [],
        analytics_channels: [],
        analytics_channels_missing: fig(null),
      },
      funnel: { ...FUNNEL, findings: [] },
      campaigns: {
        definitions: DEFS,
        reporting_currency: "AUD",
        currency_minor_units: 2,
        items: [],
      },
    });
    renderWithProviders(
      <Dashboard
        org={testOrg()}
        data={overview([]) as never}
        currency={CURRENCY}
        controls={controls}
      />,
    );
    expect(await screen.findByRole("link", { name: "Connect one" })).toBeInTheDocument();
    expect(await screen.findByText(/No campaign spent anything/)).toBeInTheDocument();
    expect(screen.queryByText("Below usual")).not.toBeInTheDocument();
  });
});

describe("HeroFlow", () => {
  it("names the four sources and the one figure, without numbers", () => {
    const { container } = render(<HeroFlow />);
    const sources = screen.getByRole("list", { name: "What AdVegaX reads" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getByText("Profit after ad spend")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d/);
  });
});
