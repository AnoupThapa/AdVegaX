import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdAccountPage } from "@/features/advertising/AdAccountPage";
import { AdAccountsPage } from "@/features/advertising/AdAccountsPage";
import { CampaignPage } from "@/features/advertising/CampaignPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { formatDay } from "@/features/stores/dates";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const ACCOUNT = "6e2d3c4b-5f6a-4b7c-8d9e-0f1a2b3c4d5e";
const CAMPAIGN = "7f3e4d5c-6a7b-4c8d-9e0f-1a2b3c4d5e6f";
const me = testUser();

const account = (extra: Record<string, unknown> = {}, sync: Record<string, unknown> = {}) => ({
  id: ACCOUNT,
  resource_id: "r-1",
  provider: "google_ads",
  source: "platform_reported",
  external_account_id: "1000000001",
  name: "Eve Zone AU",
  group_path: "Agency > Retail clients",
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  status: "active",
  platform_status: "active",
  linked: true,
  connection_status: "active",
  history_from: "2025-09-14",
  first_import_completed_at: "2026-10-14T00:00:00Z",
  created_at: "2026-10-14T00:00:00Z",
  health: { code: null, checked_at: "2026-10-14T03:00:00Z" },
  sync: {
    running: false,
    mode: null,
    progress: null,
    waiting_for_allowance: false,
    last_quick_at: "2026-10-14T03:00:00Z",
    last_nightly_at: "2026-10-14T00:00:00Z",
    last_weekly_at: "2026-10-14T00:00:00Z",
    last_error_code: null,
    last_error_at: null,
    ...sync,
  },
  ...extra,
});

const rate = (value: string | null, reason: string | null = null, availability = "available") => ({
  value,
  availability: value === null && availability === "available" ? "unavailable" : availability,
  reason,
});

const figures = (extra: Record<string, unknown> = {}) => ({
  availability: "available",
  reason: null,
  impressions: 1200,
  clicks: 34,
  cost: "12.345678",
  conversions: "1.500000",
  conversion_value: "89.900000",
  click_through_rate: rate("0.028333"),
  cost_per_click: rate("0.363108"),
  cost_per_conversion: rate("8.230452"),
  conversion_value_per_cost: rate("7.281995"),
  ...extra,
});

const quiet = () =>
  figures({
    impressions: 0,
    clicks: 0,
    cost: "0.000000",
    conversions: "0.000000",
    conversion_value: "0.000000",
    click_through_rate: rate(null, "no_impressions"),
    cost_per_click: rate(null, "no_clicks"),
    cost_per_conversion: rate(null, "no_conversions"),
    conversion_value_per_cost: rate(null, "no_cost"),
  });

const notSynced = () =>
  figures({
    availability: "not_synchronized",
    reason: "not_synchronized",
    impressions: null,
    clicks: null,
    cost: null,
    conversions: null,
    conversion_value: null,
    click_through_rate: rate(null, "not_synchronized", "not_synchronized"),
    cost_per_click: rate(null, "not_synchronized", "not_synchronized"),
    cost_per_conversion: rate(null, "not_synchronized", "not_synchronized"),
    conversion_value_per_cost: rate(null, "not_synchronized", "not_synchronized"),
  });

const metrics = (extra: Record<string, unknown> = {}) => ({
  ad_account_id: ACCOUNT,
  source: "platform_reported",
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  from_day: "2026-10-12",
  to_day: "2026-10-14",
  synced_from: "2025-09-14",
  settled_until: "2026-10-11",
  days: [
    { day: "2026-10-01", settled: true, ...figures() },
    { day: "2026-10-05", settled: true, ...quiet() },
    { day: "2026-10-14", settled: false, ...quiet() },
  ],
  totals: figures(),
  ...extra,
});

const campaign = (extra: Record<string, unknown> = {}) => ({
  id: CAMPAIGN,
  ad_account_id: ACCOUNT,
  external_id: "11",
  name: "Gloves - Search",
  status: "active",
  platform_type: "SEARCH",
  bidding_strategy_type: "MAXIMIZE_CONVERSIONS",
  start_date: "2026-01-15",
  end_date: null,
  budget: {
    name: "Gloves daily",
    period: "daily",
    amount: "50.000000",
    currency: "AUD",
    shared: true,
  },
  figures: figures(),
  ...extra,
});

const campaigns = () => ({
  ad_account_id: ACCOUNT,
  source: "platform_reported",
  currency: "AUD",
  currency_minor_units: 2,
  from_day: "2026-09-15",
  to_day: "2026-10-14",
  items: [
    campaign(),
    campaign({
      id: "c-13",
      external_id: "13",
      name: "Old test",
      status: "removed",
      platform_type: "DISPLAY",
      budget: null,
      figures: quiet(),
    }),
  ],
});

const detail = (extra: Record<string, unknown> = {}) => ({
  ...campaign(),
  provider: "google_ads",
  source: "platform_reported",
  synced_from: "2025-09-14",
  currency: "AUD",
  currency_minor_units: 2,
  from_day: "2026-09-15",
  to_day: "2026-10-14",
  ad_groups: [
    {
      id: "g-1",
      external_id: "2101",
      name: "Nitrile gloves",
      status: "active",
      platform_type: "SEARCH_STANDARD",
      budget: null,
      figures: figures(),
      ads: [
        {
          id: "a-1",
          external_id: "90001",
          name: null,
          status: "active",
          platform_type: "RESPONSIVE_SEARCH_AD",
          figures: figures(),
        },
      ],
    },
  ],
  ...extra,
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

const ACCOUNT_PATH = `${ORG_PATH}/ad-accounts/${ACCOUNT}`;

function baseApi(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...extra,
  });
}

function accountApi(role = "manager", extra: Parameters<typeof mockApi>[0] = {}) {
  return baseApi(role, {
    [`GET ${ACCOUNT_PATH}`]: ok(account()),
    [`GET ${ACCOUNT_PATH}/metrics/daily`]: ok(metrics()),
    [`GET ${ACCOUNT_PATH}/campaigns`]: ok(campaigns()),
    ...extra,
  });
}

function renderAccount() {
  renderWithProviders(
    inShell(<AdAccountPage />, `/orgs/${ORG_ID}/advertising/${ACCOUNT}`, { adAccountId: ACCOUNT }),
    { session: me },
  );
}

describe("Advertising tab", () => {
  it("lists ad accounts with their status and an Advertising tab", async () => {
    baseApi("viewer", {
      [`GET ${ORG_PATH}/ad-accounts`]: ok([
        account(),
        account(
          { id: "a2", name: "Eve Zone NZ", status: "importing", first_import_completed_at: null },
          { running: true, mode: "initial", progress: 55 },
        ),
        account(
          { id: "a3", name: "Waiting one" },
          { running: true, mode: "nightly", waiting_for_allowance: true },
        ),
      ]),
    });
    renderWithProviders(inShell(<AdAccountsPage />, `/orgs/${ORG_ID}/advertising`), {
      session: me,
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Advertising" }),
    ).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Organization" });
    expect(within(nav).getByRole("link", { name: "Advertising" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("link", { name: "Eve Zone AU" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/advertising/${ACCOUNT}`,
    );
    expect(screen.getAllByText(/Google Ads · AUD · Australia\/Sydney/)).toHaveLength(3);
    expect(screen.getByText("Up to date")).toBeInTheDocument();
    expect(
      screen.getByText(/Importing campaigns and 13 months of figures \(55%\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Waiting for Google's daily limit/)).toBeInTheDocument();
  });

  it("explains how to add an ad account when there is none", async () => {
    baseApi("viewer", { [`GET ${ORG_PATH}/ad-accounts`]: ok([]) });
    renderWithProviders(inShell(<AdAccountsPage />, `/orgs/${ORG_ID}/advertising`), {
      session: me,
    });
    expect(await screen.findByText("No ad accounts yet.")).toBeInTheDocument();
    const empty = screen.getByText("No ad accounts yet.").closest("div") as HTMLElement;
    expect(within(empty).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
    expect(screen.getByText(/never changes anything/)).toBeInTheDocument();
  });
});

describe("Ad account page", () => {
  it("shows Google's figures with exact money, derived rates and their reasons", async () => {
    accountApi();
    renderAccount();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Eve Zone AU" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Agency › Retail clients")).toBeInTheDocument();
    expect(screen.getAllByText(/Reported by Google Ads/).length).toBeGreaterThanOrEqual(2);
    const totals = await screen.findByRole("list", { name: "Totals for the period" });
    const tile = (label: string) => within(totals).getByText(label).closest("li") as HTMLElement;
    expect(tile("Spend")).toHaveTextContent(/\$12\.35$/);
    expect(tile("Clicks")).toHaveTextContent("34");
    expect(tile("Impressions")).toHaveTextContent(/1,200$/);
    expect(tile("Conversions")).toHaveTextContent(/1\.5$/);
    expect(tile("Click-through rate")).toHaveTextContent(/2\.8%$/);
    expect(tile("Cost per click")).toHaveTextContent(/\$0\.36$/);
    expect(tile("Cost per conversion")).toHaveTextContent(/\$8\.23$/);
    expect(tile("Conversion value per AUD spent")).toHaveTextContent(/7\.28$/);
    const daily = screen.getByRole("table", { name: /Each day in the ad account's time zone/ });
    const today = within(daily).getByRole("row", { name: new RegExp(formatDay("2026-10-14")) });
    expect(today).toHaveTextContent("may still change");
    const settled = within(daily).getByRole("row", { name: new RegExp(formatDay("2026-10-05")) });
    expect(settled).not.toHaveTextContent("may still change");
    expect(settled).toHaveTextContent("$0.00"); // read, no activity: a real zero
  });

  it("lists campaigns with budget, status and their own figures", async () => {
    accountApi();
    renderAccount();
    const table = await screen.findByRole("table", { name: /Campaigns with their own figures/ });
    const search = within(table).getByRole("row", { name: /Gloves - Search/ });
    expect(within(search).getByRole("link", { name: "Gloves - Search" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/advertising/campaigns/${CAMPAIGN}?from=2026-09-15&to=2026-10-14`,
    );
    expect(search).toHaveTextContent("Search");
    expect(search).toHaveTextContent("$50.00 a day (shared)");
    expect(search).toHaveTextContent("$12.35");
    const old = within(table).getByRole("row", { name: /Old test/ });
    expect(old).toHaveTextContent("Removed");
    expect(old).toHaveTextContent("No budget");
    expect(old).toHaveTextContent("No impressions"); // the rate cannot exist: says why
  });

  it("never shows 0 for days that were not read", async () => {
    accountApi("viewer", {
      [`GET ${ACCOUNT_PATH}/metrics/daily`]: ok(
        metrics({
          days: [{ day: "2025-09-13", settled: true, ...notSynced() }],
          totals: notSynced(),
        }),
      ),
    });
    renderAccount();
    expect(await screen.findByText(/Part of this period is before/)).toBeInTheDocument();
    const totals = screen.getByRole("list", { name: "Totals for the period" });
    expect(within(totals).getAllByText("Not synced yet").length).toBe(9);
    expect(within(totals).queryByText(/\$0\.00/)).toBeNull();
  });

  it("asks for a new period when the select changes", async () => {
    const api = accountApi();
    renderAccount();
    await screen.findByRole("list", { name: "Totals for the period" });
    fill(screen.getByLabelText("Period"), "7");
    await waitFor(() =>
      expect(api.apiCalls().filter((c) => c.path === `${ACCOUNT_PATH}/metrics/daily`).length).toBe(
        2,
      ),
    );
  });

  it("explains health problems with the fix", async () => {
    accountApi("viewer", {
      [`GET ${ACCOUNT_PATH}`]: ok(
        account(
          { health: { code: "no_account_access", checked_at: "2026-10-14T03:00:00Z" } },
          { last_error_code: "no_account_access" },
        ),
      ),
    });
    renderAccount();
    expect(
      await screen.findByRole("heading", { name: "AdVegaX can no longer read this ad account" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Ask the ad account's administrator/)).toBeInTheDocument();
  });

  it("managers can sync now; the result is reported", async () => {
    const api = accountApi("manager", {
      [`POST ${ACCOUNT_PATH}/resync`]: ok(
        { ad_account_id: ACCOUNT, job_id: "j1", mode: "nightly" },
        202,
      ),
    });
    renderAccount();
    click(await screen.findByRole("button", { name: "Sync now" }));
    expect(
      await screen.findByText(/campaigns and the last 30 days are read again/),
    ).toBeInTheDocument();
    const post = api.apiCalls().find((c) => c.method === "POST");
    expect(post?.csrf).toBe("csrf-test");
  });

  it("shows why Sync now was refused", async () => {
    accountApi("owner", { [`POST ${ACCOUNT_PATH}/resync`]: fail(429, "RATE_LIMITED") });
    renderAccount();
    click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("viewers do not see Sync now; unlinked accounts stay readable", async () => {
    accountApi("viewer", { [`GET ${ACCOUNT_PATH}`]: ok(account({ linked: false })) });
    renderAccount();
    expect(await screen.findByText(/This ad account is not linked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
    expect(await screen.findByRole("list", { name: "Totals for the period" })).toBeInTheDocument();
  });

  it("is not found for malformed ids and other organizations' accounts", async () => {
    baseApi("owner", { [`GET ${ACCOUNT_PATH}`]: fail(404, "NOT_FOUND") });
    renderAccount();
    expect(
      await screen.findByRole("heading", { name: "Ad account not found" }),
    ).toBeInTheDocument();
  });
});

describe("Campaign page", () => {
  const CAMPAIGN_PATH = `${ORG_PATH}/campaigns/${CAMPAIGN}`;

  function renderCampaign(search = "") {
    navigation.search = search;
    renderWithProviders(
      inShell(<CampaignPage />, `/orgs/${ORG_ID}/advertising/campaigns/${CAMPAIGN}`, {
        campaignId: CAMPAIGN,
      }),
      { session: me },
    );
  }

  it("shows budget, ad groups and ads, each with its own figures", async () => {
    const api = baseApi("viewer", { [`GET ${CAMPAIGN_PATH}`]: ok(detail()) });
    renderCampaign("?from=2026-09-15&to=2026-10-14");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Gloves - Search" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/\$50\.00 a day \(shared\) — Gloves daily/)).toBeInTheDocument();
    expect(screen.getByText("Maximize conversions")).toBeInTheDocument();
    expect(screen.getByText(/no end date/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: /Nitrile gloves/ })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Totals for Nitrile gloves" })).toBeInTheDocument();
    const ads = screen.getByRole("table", { name: "Ads in Nitrile gloves" });
    expect(within(ads).getByRole("row", { name: /Ad 90001/ })).toHaveTextContent("$12.35");
    expect(screen.getAllByText(/Reported by Google Ads/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("link", { name: "← Ad account" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/advertising/${ACCOUNT}`,
    );
    const call = api.apiCalls().find((c) => c.path === CAMPAIGN_PATH);
    expect(call).toBeDefined();
  });

  it("explains campaigns without ad groups", async () => {
    baseApi("viewer", {
      [`GET ${CAMPAIGN_PATH}`]: ok(
        detail({ name: "Spring - PMax", platform_type: "PERFORMANCE_MAX", ad_groups: [] }),
      ),
    });
    renderCampaign();
    expect(
      await screen.findByText(/report figures only for the whole campaign/),
    ).toBeInTheDocument();
    expect(screen.getByText("Performance max")).toBeInTheDocument();
  });

  it("is not found for other organizations' campaigns", async () => {
    baseApi("viewer", { [`GET ${CAMPAIGN_PATH}`]: fail(404, "NOT_FOUND") });
    renderCampaign();
    expect(await screen.findByRole("heading", { name: "Campaign not found" })).toBeInTheDocument();
  });
});
