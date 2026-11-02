import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsPropertiesPage } from "@/features/analytics/AnalyticsPropertiesPage";
import { AnalyticsPropertyPage } from "@/features/analytics/AnalyticsPropertyPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { formatDay } from "@/features/stores/dates";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok, type MockCall } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const PROPERTY = "8a4f5e6d-7b8c-4d9e-8f0a-1b2c3d4e5f6a";
const PROPERTY_PATH = `${ORG_PATH}/analytics-properties/${PROPERTY}`;
const me = testUser();

const property = (extra: Record<string, unknown> = {}, sync: Record<string, unknown> = {}) => ({
  id: PROPERTY,
  resource_id: "r-1",
  provider: "google_analytics",
  source: "platform_reported",
  external_property_id: "111",
  name: "Eve Zone AU",
  account_name: "Eve Zone",
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

const figure = (
  value: string | null,
  reason: string | null = null,
  availability = "available",
) => ({
  value,
  availability: value === null && availability === "available" ? "unavailable" : availability,
  reason,
});

const quality = (extra: Record<string, boolean> = {}) => ({
  other_row: false,
  thresholded: false,
  sampled: false,
  truncated: false,
  ...extra,
});

const figures = (extra: Record<string, unknown> = {}) => ({
  availability: "available",
  reason: null,
  sessions: 1234,
  engaged_sessions: 800,
  total_users: figure("11"),
  new_users: 300,
  key_events: "45.500000",
  purchases: 12,
  purchase_revenue: "1520.455000",
  engagement_rate: figure("0.648298"),
  key_events_per_session: figure("0.036872"),
  purchase_conversion_rate: figure("0.009724"),
  revenue_per_session: figure("1.232135"),
  quality: quality(),
  ...extra,
});

const quiet = () =>
  figures({
    sessions: 0,
    engaged_sessions: 0,
    total_users: figure("0"),
    new_users: 0,
    key_events: "0.000000",
    purchases: 0,
    purchase_revenue: "0.000000",
    engagement_rate: figure(null, "no_sessions"),
    key_events_per_session: figure(null, "no_sessions"),
    purchase_conversion_rate: figure(null, "no_sessions"),
    revenue_per_session: figure(null, "no_sessions"),
  });

const notSynced = () =>
  figures({
    availability: "not_synchronized",
    reason: "not_synchronized",
    sessions: null,
    engaged_sessions: null,
    total_users: figure(null, "not_synchronized", "not_synchronized"),
    new_users: null,
    key_events: null,
    purchases: null,
    purchase_revenue: null,
    engagement_rate: figure(null, "not_synchronized", "not_synchronized"),
    key_events_per_session: figure(null, "not_synchronized", "not_synchronized"),
    purchase_conversion_rate: figure(null, "not_synchronized", "not_synchronized"),
    revenue_per_session: figure(null, "not_synchronized", "not_synchronized"),
  });

const metrics = (extra: Record<string, unknown> = {}) => ({
  property_id: PROPERTY,
  source: "platform_reported",
  breakdown: "total",
  currency: "AUD",
  currency_minor_units: 2,
  timezone: "Australia/Sydney",
  from_day: "2026-09-15",
  to_day: "2026-10-14",
  synced_from: "2025-09-14",
  processing_from: "2026-10-12",
  totals: figures({ total_users: figure(null, "users_per_day_only") }),
  days: [
    {
      day: "2026-10-01",
      processing: false,
      ...figures({ quality: quality({ thresholded: true }) }),
    },
    { day: "2026-10-05", processing: false, ...quiet() },
    { day: "2026-10-14", processing: true, ...quiet() },
  ],
  items: [],
  item_count: 0,
  ...extra,
});

const item = (key: string, extra: Record<string, unknown> = {}) => ({
  key,
  channel_group: null,
  source: null,
  medium: null,
  campaign: null,
  figures: figures({ total_users: figure(null, "users_per_day_only") }),
  ...extra,
});

const breakdowns: Record<string, unknown> = {
  total: metrics(),
  channel: metrics({
    breakdown: "channel",
    days: [],
    items: [
      item("Organic Search", { channel_group: "Organic Search" }),
      item("Paid Search", {
        channel_group: "Paid Search",
        figures: figures({ sessions: 50, purchase_revenue: "120.500000" }),
      }),
    ],
    item_count: 2,
  }),
  source: metrics({
    breakdown: "source",
    days: [],
    items: [
      item("google|cpc|Spring Sale", { source: "google", medium: "cpc", campaign: "Spring Sale" }),
    ],
    item_count: 640,
  }),
};

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

function propertyApi(role = "manager", extra: Parameters<typeof mockApi>[0] = {}) {
  return baseApi(role, {
    [`GET ${PROPERTY_PATH}`]: ok(property()),
    [`GET ${PROPERTY_PATH}/metrics/daily`]: (call: MockCall) =>
      ok(breakdowns[call.query.get("breakdown") ?? "total"]),
    ...extra,
  });
}

function renderProperty() {
  renderWithProviders(
    inShell(<AnalyticsPropertyPage />, `/orgs/${ORG_ID}/analytics/${PROPERTY}`, {
      propertyId: PROPERTY,
    }),
    { session: me },
  );
}

describe("Analytics tab", () => {
  it("lists properties with their status and an Analytics tab", async () => {
    baseApi("viewer", {
      [`GET ${ORG_PATH}/analytics-properties`]: ok([
        property(),
        property(
          { id: "p2", name: "Eve Zone NZ", status: "importing", first_import_completed_at: null },
          { running: true, mode: "initial", progress: 40 },
        ),
        property(
          { id: "p3", name: "Waiting one", health: { code: "rate_limited", checked_at: null } },
          { running: true, mode: "nightly", waiting_for_allowance: true },
        ),
      ]),
    });
    renderWithProviders(inShell(<AnalyticsPropertiesPage />, `/orgs/${ORG_ID}/analytics`), {
      session: me,
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Analytics" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Organization" });
    expect(within(nav).getByRole("link", { name: "Analytics" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByRole("link", { name: "Eve Zone AU" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/analytics/${PROPERTY}`,
    );
    expect(
      screen.getAllByText(/Google Analytics · Eve Zone · AUD · Australia\/Sydney/),
    ).toHaveLength(3);
    expect(screen.getByText("Up to date")).toBeInTheDocument();
    expect(screen.getByText(/Importing 13 months of figures \(40%\)/)).toBeInTheDocument();
    expect(screen.getByText(/Google is limiting how much AdVegaX can read/)).toBeInTheDocument();
    expect(screen.getByText("Waiting")).toBeInTheDocument();
  });

  it("explains how to add a property when there is none", async () => {
    baseApi("viewer", { [`GET ${ORG_PATH}/analytics-properties`]: ok([]) });
    renderWithProviders(inShell(<AnalyticsPropertiesPage />, `/orgs/${ORG_ID}/analytics`), {
      session: me,
    });
    expect(await screen.findByText("No analytics properties yet.")).toBeInTheDocument();
    const empty = screen.getByText("No analytics properties yet.").closest("div") as HTMLElement;
    expect(within(empty).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
    expect(screen.getByText(/never changes anything/)).toBeInTheDocument();
  });
});

describe("Property page", () => {
  it("shows Google Analytics figures with exact money, rates, and users per day only", async () => {
    propertyApi();
    renderProperty();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Eve Zone AU" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Reported by Google Analytics/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Analytics account")).toBeInTheDocument();
    const totals = await screen.findByRole("list", { name: "Totals for the period" });
    const tile = (label: string) => within(totals).getByText(label).closest("li") as HTMLElement;
    expect(tile("Sessions")).toHaveTextContent(/1,234$/);
    expect(tile("Users")).toHaveTextContent("Shown per day only");
    expect(tile("Users")).toHaveTextContent(/never added up/);
    expect(tile("New users")).toHaveTextContent(/300$/);
    expect(tile("Key events")).toHaveTextContent(/45\.5$/);
    expect(tile("Purchase revenue")).toHaveTextContent("$1,520.46"); // half-even, for display
    expect(tile("Purchase revenue")).toHaveTextContent(/minus refunds/);
    expect(tile("Engagement rate")).toHaveTextContent(/64\.8%$/);
    expect(tile("Purchase conversion rate")).toHaveTextContent(/1\.0%$/);
    expect(tile("Revenue per session")).toHaveTextContent(/\$1\.23$/);
    const daily = screen.getByRole("table", { name: /Each day in the property's time zone/ });
    const today = within(daily).getByRole("row", { name: new RegExp(formatDay("2026-10-14")) });
    expect(today).toHaveTextContent("still being processed");
    const first = within(daily).getByRole("row", { name: new RegExp(formatDay("2026-10-01")) });
    expect(first).toHaveTextContent("11"); // the day's own users
    expect(first).toHaveTextContent(/withheld some small numbers/);
    const quietDay = within(daily).getByRole("row", { name: new RegExp(formatDay("2026-10-05")) });
    expect(quietDay).toHaveTextContent("$0.00"); // read, no activity: a real zero
    const notes = screen.getByRole("list", { name: "Notes about these figures" });
    expect(notes).toHaveTextContent(/still being processed by Google/);
  });

  it("shows where visits came from, by channel and by source", async () => {
    const api = propertyApi();
    renderProperty();
    const channels = await screen.findByRole("table", { name: /Channels with their own figures/ });
    const paid = within(channels).getByRole("row", { name: /Paid Search/ });
    expect(paid).toHaveTextContent("50");
    expect(paid).toHaveTextContent("$120.50");
    fill(screen.getByLabelText("Show"), "source");
    const sources = await screen.findByRole("table", { name: /Sources, mediums and campaigns/ });
    expect(sources).toHaveTextContent("Showing the 1 largest of 640.");
    const row = within(sources).getByRole("row", { name: /google \/ cpc/ });
    expect(row).toHaveTextContent("Spring Sale");
    const asked = api
      .apiCalls()
      .filter((c) => c.path === `${PROPERTY_PATH}/metrics/daily`)
      .map((c) => c.query.get("breakdown"));
    expect(new Set(asked)).toEqual(new Set(["total", "channel", "source"]));
  });

  it("never shows 0 for days that were not read", async () => {
    propertyApi("viewer", {
      [`GET ${PROPERTY_PATH}/metrics/daily`]: (call: MockCall) =>
        ok(
          metrics({
            breakdown: call.query.get("breakdown"),
            days:
              call.query.get("breakdown") === "total"
                ? [{ day: "2025-09-13", processing: false, ...notSynced() }]
                : [],
            totals: notSynced(),
          }),
        ),
    });
    renderProperty();
    expect(await screen.findByText(/Part of this period is before/)).toBeInTheDocument();
    const totals = screen.getByRole("list", { name: "Totals for the period" });
    expect(within(totals).getAllByText("Not synced yet").length).toBe(11);
    expect(within(totals).queryByText(/\$0\.00/)).toBeNull();
    expect(screen.getByText("Not available for this period.")).toBeInTheDocument();
  });

  it("asks for a new period when the select changes", async () => {
    const api = propertyApi();
    renderProperty();
    await screen.findByRole("list", { name: "Totals for the period" });
    fill(screen.getByLabelText("Period"), "7");
    await waitFor(() =>
      expect(
        api
          .apiCalls()
          .filter(
            (c) =>
              c.path === `${PROPERTY_PATH}/metrics/daily` && c.query.get("breakdown") === "total",
          ).length,
      ).toBe(2),
    );
  });

  it.each([
    ["no_property_access", "You no longer have access to this property", /Viewer access/],
    ["property_deleted", "This property was deleted in Google Analytics", /Trash/],
    ["rate_limited", "Google is limiting how much AdVegaX can read", /No action is needed/],
  ])("explains %s with the fix", async (code, title, fix) => {
    propertyApi("viewer", {
      [`GET ${PROPERTY_PATH}`]: ok(
        property({ health: { code, checked_at: "2026-10-14T03:00:00Z" } }),
      ),
    });
    renderProperty();
    expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText(fix)).toBeInTheDocument();
  });

  it("says when the Google sign-in needs reconnecting", async () => {
    propertyApi("owner", {
      [`GET ${PROPERTY_PATH}`]: ok(property({ connection_status: "expired" })),
    });
    renderProperty();
    expect(await screen.findByText(/needs reconnecting/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconnect Google Analytics" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
  });

  it("managers can sync now; the result is reported", async () => {
    const api = propertyApi("manager", {
      [`POST ${PROPERTY_PATH}/resync`]: ok(
        { property_id: PROPERTY, job_id: "j1", mode: "nightly" },
        202,
      ),
    });
    renderProperty();
    click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByText(/the last 14 days are read again/)).toBeInTheDocument();
    const post = api.apiCalls().find((c) => c.method === "POST");
    expect(post?.csrf).toBe("csrf-test");
  });

  it("shows why Sync now was refused", async () => {
    propertyApi("owner", {
      [`POST ${PROPERTY_PATH}/resync`]: fail(409, "ANALYTICS_PROPERTY_NOT_SYNCING"),
    });
    renderProperty();
    click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByText(/not linked to an active connection/)).toBeInTheDocument();
  });

  it("viewers do not see Sync now; unlinked properties stay readable", async () => {
    propertyApi("viewer", { [`GET ${PROPERTY_PATH}`]: ok(property({ linked: false })) });
    renderProperty();
    expect(await screen.findByText(/This property is not linked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).toBeNull();
    expect(await screen.findByRole("list", { name: "Totals for the period" })).toBeInTheDocument();
  });

  it("is not found for malformed ids and other organizations' properties", async () => {
    baseApi("owner", { [`GET ${PROPERTY_PATH}`]: fail(404, "NOT_FOUND") });
    renderProperty();
    expect(await screen.findByRole("heading", { name: "Property not found" })).toBeInTheDocument();
  });
});
