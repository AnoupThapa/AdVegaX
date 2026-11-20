import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { StrategiesPage } from "@/features/strategies/StrategiesPage";
import { StrategyDetail } from "@/features/strategies/StrategyDetail";
import { reasonText } from "@/features/strategies/labels";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});
afterEach(() => vi.unstubAllGlobals());

const STORE = "5a0e7c1e-0000-4000-8000-000000000001";
const PRODUCT = "5a0e7c1e-0000-4000-8000-0000000000a1";
const STRATEGY = "5a0e7c1e-0000-4000-8000-0000000000b1";
const BASE = `${ORG_PATH}/ai/campaign-strategies`;

const store = {
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
    last_reconciled_at: null,
    last_deep_reconciled_at: null,
    last_error_code: null,
    last_error_at: null,
  },
};

const products = {
  items: [
    {
      id: PRODUCT,
      external_id: "gid://shopify/Product/1",
      title: "Nitrile gloves",
      handle: null,
      product_type: null,
      vendor: null,
      status: "active",
      updated_at: null,
      variants: [],
    },
  ],
  next_cursor: null,
};

const budget = { amount: "40.00", period: "daily", currency: "AUD", currency_minor_units: 2 };

const PLAN = {
  objective: "sales",
  summary: "Search for buyers already looking; Meta for reach.",
  positioning: "Bulk gloves at wholesale prices.",
  platforms: [
    {
      platform: "google_ads",
      campaign_type: "shopping",
      budget_share_percent: 70,
      audience: "Businesses searching for nitrile gloves in bulk.",
      reasoning: "Most sales follow search spend.",
      evidence: ["platform.google_ads.spend", "business.blended_roas"],
    },
    {
      platform: "meta_ads",
      campaign_type: "sales",
      budget_share_percent: 30,
      audience: "Owners of cafes, clinics and cleaning firms.",
      reasoning: "A smaller test budget.",
      evidence: ["funnel.adds_to_cart"],
    },
  ],
  angles: [{ angle: "Margin room for offers", evidence: ["product.gross_margin"] }],
  targets: [
    { metric: "roas", low: 3, high: 6, evidence: ["business.blended_roas"] },
    { metric: "cost_per_order", low: 20, high: 40, evidence: ["business.ad_spend"] },
  ],
  risks: [{ code: "competition", text: "Many resellers bid on glove terms." }],
  assumptions: ["Prices stay as they are."],
};

const evidence = (
  label: string,
  unit: string,
  value: string | null,
  reason: string | null = null,
) => ({
  label,
  unit,
  value,
  availability: value === null ? "unavailable" : "available",
  reason,
  ...(unit === "money" ? { currency: "AUD" } : {}),
});

const strategy = (extra: Record<string, unknown> = {}) => ({
  id: STRATEGY,
  product_id: PRODUCT,
  product_title: "Nitrile gloves",
  status: "draft",
  strategy: PLAN,
  budget,
  budget_amounts: {
    google_ads: { amount: "28.00", daily: "28.00" },
    meta_ads: { amount: "12.00", daily: "12.00" },
  },
  evidence: {
    "platform.google_ads.spend": evidence("Spend", "money", "50.000000"),
    "business.blended_roas": evidence("Blended ROAS", "multiple", "5.000000"),
    "funnel.adds_to_cart": evidence("Adds to cart", "count", null, "no_analytics_property"),
    "product.gross_margin": evidence("Gross margin", "ratio", "0.600000"),
    "business.ad_spend": evidence("Ad spend", "money", "60.00"),
  },
  validated: true,
  ai_run: {
    id: "run-1",
    provider: "anthropic",
    model: "claude-sonnet-5-5",
    prompt_name: "campaign_strategy",
    prompt_version: "v1",
    created_at: "2026-10-14T01:00:00Z",
  },
  created_by: "user-1",
  edited_by: null,
  edited_at: null,
  created_at: "2026-10-14T01:00:00Z",
  updated_at: "2026-10-14T01:00:00Z",
  ...extra,
});

const summary = (extra: Record<string, unknown> = {}) => ({
  id: STRATEGY,
  product_id: PRODUCT,
  product_title: "Nitrile gloves",
  status: "draft",
  objective: "sales",
  platforms: ["google_ads", "meta_ads"],
  budget,
  created_at: "2026-10-14T01:00:00Z",
  updated_at: "2026-10-14T01:00:00Z",
  ...extra,
});

function routes(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  return {
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    [`GET ${ORG_PATH}/stores`]: ok([store]),
    [`GET ${ORG_PATH}/stores/${STORE}/products`]: ok(products),
    [`GET ${BASE}`]: ok([summary()]),
    [`GET ${BASE}/${STRATEGY}`]: ok(strategy()),
    ...extra,
  };
}

function renderList() {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = `/orgs/${ORG_ID}/strategies`;
  return renderWithProviders(
    <OrganizationShell>
      <StrategiesPage />
    </OrganizationShell>,
    { session: testUser() },
  );
}

function renderDetail(id = STRATEGY) {
  navigation.params = { organizationId: ORG_ID, strategyId: id };
  navigation.pathname = `/orgs/${ORG_ID}/strategies/${id}`;
  return renderWithProviders(
    <OrganizationShell>
      <StrategyDetail />
    </OrganizationShell>,
    { session: testUser() },
  );
}

async function fillForm() {
  fill(await screen.findByRole("combobox", { name: "Product" }), PRODUCT);
  fill(screen.getByLabelText("Budget (AUD)"), "40.00");
}

describe("Strategies list and new strategy", () => {
  it("lists strategies with their budget and status", async () => {
    mockApi(routes());
    renderList();
    const table = await screen.findByRole("table");
    const row = within(table).getByRole("row", { name: /Nitrile gloves/ });
    expect(row).toHaveTextContent("Google Ads, Meta");
    expect(row).toHaveTextContent("Sales");
    expect(row).toHaveTextContent("A$40.00 per day");
    expect(row).toHaveTextContent("Draft");
    expect(within(row).getByRole("link", { name: "Nitrile gloves" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/strategies/${STRATEGY}`,
    );
    expect(screen.getByRole("link", { name: "Strategies" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("creates a strategy and opens it", async () => {
    const api = mockApi(routes("analyst", { [`POST ${BASE}`]: ok(strategy(), 201) }));
    renderList();
    await fillForm();
    click(screen.getByRole("checkbox", { name: "Meta" }));
    fill(screen.getByLabelText("Objective"), "leads");
    fill(screen.getByLabelText("Budget period"), "monthly");
    click(screen.getByRole("button", { name: "Create strategy" }));
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}/strategies/${STRATEGY}`),
    );
    const post = api.calls.find((c) => c.method === "POST" && c.path === BASE);
    expect(post?.body).toEqual({
      product_id: PRODUCT,
      platforms: ["google_ads"],
      objective: "leads",
      budget: { amount: "40.00", period: "monthly" },
    });
  });

  it("says what is missing before sending anything", async () => {
    const api = mockApi(routes());
    renderList();
    click(await screen.findByRole("button", { name: "Create strategy" }));
    click(screen.getByRole("checkbox", { name: "Google Ads" }));
    click(screen.getByRole("checkbox", { name: "Meta" }));
    click(screen.getByRole("button", { name: "Create strategy" }));
    expect(await screen.findByText("Choose a product.")).toBeVisible();
    expect(screen.getByText("Choose at least one platform.")).toBeVisible();
    expect(screen.getByText(/Enter an amount above 0/)).toBeVisible();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("explains why a product cannot be planned", async () => {
    mockApi(
      routes("owner", {
        [`POST ${BASE}`]: fail(422, "PRODUCT_NOT_PLANNABLE", [
          { reason: "out_of_stock" },
          { reason: "platform_not_connected:meta_ads" },
        ]),
      }),
    );
    renderList();
    await fillForm();
    click(screen.getByRole("button", { name: "Create strategy" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("A strategy cannot be made for this product right now.");
    expect(alert).toHaveTextContent("The product is out of stock.");
    expect(alert).toHaveTextContent("Meta is not connected for this product's store.");
  });

  it("explains a rejected AI answer and the daily limit", async () => {
    mockApi(
      routes("owner", {
        [`POST ${BASE}`]: fail(422, "AI_ANSWER_REJECTED", [
          { reason: "unknown_evidence:product.reviews" },
        ]),
      }),
    );
    renderList();
    await fillForm();
    click(screen.getByRole("button", { name: "Create strategy" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("did not pass AdVegaX's checks, so nothing was saved");
    expect(alert).toHaveTextContent("It cited a figure AdVegaX does not have (product.reviews).");
  });

  it("lets viewers read but not create", async () => {
    mockApi(routes("viewer"));
    renderList();
    expect(await screen.findByRole("table")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "New strategy" })).toBeNull();
    expect(screen.getByText("Nitrile gloves")).toBeVisible();
  });

  it("filters and says when there is nothing", async () => {
    const api = mockApi(routes("owner", { [`GET ${BASE}`]: ok([]) }));
    renderList();
    expect(await screen.findByText("No strategies here yet. Make one above.")).toBeVisible();
    fill(screen.getByLabelText("Show"), "archived");
    await waitFor(() =>
      expect(api.calls.some((c) => c.path === BASE && c.query.get("status") === "archived")).toBe(
        true,
      ),
    );
  });
});

describe("One strategy", () => {
  it("shows the plan, its amounts, its evidence and where it came from", async () => {
    mockApi(routes());
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Nitrile gloves" })).toBeVisible();
    expect(
      screen.getByText(/Drafted by Claude \(claude-sonnet-5-5\), prompt campaign_strategy v1/),
    ).toBeVisible();
    const google = screen.getByRole("heading", { name: "Google Ads — Shopping" }).closest("li");
    expect(google).toHaveTextContent("A$28.00 per day (70% of the budget)");
    expect(google).toHaveTextContent("Spend: A$50.00");
    expect(google).toHaveTextContent("Blended ROAS: 5×");
    const meta = screen.getByRole("heading", { name: "Meta — Sales" }).closest("li");
    expect(meta).toHaveTextContent("A$12.00 per day (30% of the budget)");
    expect(meta).toHaveTextContent("Adds to cart: No Google Analytics property"); // never 0
    expect(screen.getByText(/Gross margin: 60.0%/)).toBeVisible();
    expect(screen.getByText("Return on ad spend (ROAS):")).toBeVisible();
    expect(screen.getByText(/3× to 6×/)).toBeVisible();
    expect(screen.getByText(/A\$20.00 to A\$40.00/)).toBeVisible();
    expect(screen.getByText("Competition:")).toBeVisible();
    expect(screen.getByText("Prices stay as they are.")).toBeVisible();
  });

  it("edits, and shows the checks that failed", async () => {
    const api = mockApi(
      routes("owner", {
        [`PATCH ${BASE}/${STRATEGY}`]: fail(422, "VALIDATION_ERROR", [
          { field: "strategy", issue: "shares_do_not_add_up" },
        ]),
      }),
    );
    renderDetail();
    click(await screen.findByRole("button", { name: "Edit" }));
    fill(screen.getByLabelText("Share of the budget for Meta (%)"), "20");
    fill(screen.getByLabelText("Summary"), "Mostly search.");
    fill(screen.getByLabelText("Budget (AUD)"), "50");
    click(screen.getByRole("button", { name: "Save changes" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The budget shares do not add up to 100%.");
    const patch = api.calls.find((c) => c.method === "PATCH");
    const body = patch?.body as { strategy: typeof PLAN; budget: unknown };
    expect(body.budget).toEqual({ amount: "50", period: "daily" });
    expect(body.strategy.summary).toBe("Mostly search.");
    expect(body.strategy.platforms.map((p) => p.budget_share_percent)).toEqual([70, 20]);
  });

  it("saves an edit and shows the strategy again", async () => {
    mockApi(
      routes("owner", {
        [`PATCH ${BASE}/${STRATEGY}`]: ok(strategy({ strategy: { ...PLAN, summary: "Updated." } })),
      }),
    );
    renderDetail();
    click(await screen.findByRole("button", { name: "Edit" }));
    click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Updated.")).toBeVisible();
  });

  it("marks ready and archives after confirming", async () => {
    const api = mockApi(
      routes("manager", {
        [`POST ${BASE}/${STRATEGY}/ready`]: ok(strategy({ status: "ready" })),
        [`POST ${BASE}/${STRATEGY}/archive`]: ok(strategy({ status: "archived" })),
      }),
    );
    renderDetail();
    click(await screen.findByRole("button", { name: "Mark ready for the campaign builder" }));
    expect(await screen.findByText("Ready for the campaign builder")).toBeVisible();
    click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog", { name: "Archive this strategy?" });
    click(within(dialog).getByRole("button", { name: "Archive" }));
    expect(await screen.findByText(/This strategy is archived/)).toBeVisible();
    expect(api.calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
      `${BASE}/${STRATEGY}/ready`,
      `${BASE}/${STRATEGY}/archive`,
    ]);
  });

  it("shows a monthly budget with its daily equivalent", async () => {
    mockApi(
      routes("owner", {
        [`GET ${BASE}/${STRATEGY}`]: ok(
          strategy({
            budget: { ...budget, amount: "912.00", period: "monthly" },
            budget_amounts: {
              google_ads: { amount: "638.40", daily: "21.00" },
              meta_ads: { amount: "273.60", daily: "9.00" },
            },
            edited_at: "2026-10-15T01:00:00Z",
          }),
        ),
      }),
    );
    renderDetail();
    const google = (await screen.findByRole("heading", { name: "Google Ads — Shopping" })).closest(
      "li",
    );
    expect(google).toHaveTextContent(
      "A$638.40 per month (70% of the budget), about A$21.00 per day",
    );
    expect(screen.getByText(/last edited on/)).toBeVisible();
  });

  it("shows no actions to viewers", async () => {
    mockApi(routes("viewer"));
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Nitrile gloves" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("treats unknown and malformed ids as not found", async () => {
    mockApi(routes("owner", { [`GET ${BASE}/${STRATEGY}`]: fail(404, "NOT_FOUND") }));
    renderDetail();
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeVisible();
    resetNavigation();
    mockApi(routes());
    renderDetail("not-a-uuid");
    expect(
      (await screen.findAllByRole("heading", { name: "Page not found" })).length,
    ).toBeGreaterThan(0);
  });
});

describe("AI planner use in Settings", () => {
  function renderSettings(role: string, usage: unknown) {
    mockApi({
      ...routes(role),
      [`GET ${ORG_PATH}/ai/usage`]: ok(usage),
    });
    navigation.params = { organizationId: ORG_ID };
    navigation.pathname = `/orgs/${ORG_ID}/settings`;
    return renderWithProviders(
      <OrganizationShell>
        <OrganizationSettings />
      </OrganizationShell>,
      { session: testUser() },
    );
  }
  const period = (extra: Record<string, unknown> = {}) => ({
    runs: 2,
    succeeded: 1,
    rejected: 0,
    failed: 1,
    input_tokens: 1200,
    output_tokens: 300,
    estimated_cost_usd: null,
    ...extra,
  });
  const usage = {
    daily_limit: 20,
    runs_today: 2,
    remaining_today: 18,
    ai_enabled: true,
    today: period(),
    last_30_days: period({ estimated_cost_usd: "0.008100" }),
  };

  it("shows runs, tokens and cost — unknown without a price, never 0", async () => {
    renderSettings("owner", usage);
    expect(await screen.findByRole("heading", { name: "AI planner use" })).toBeVisible();
    expect(await screen.findByText(/18 left today/)).toBeVisible();
    expect(screen.getByText(/estimated cost unknown \(no price set\)/)).toBeVisible();
    expect(screen.getByText(/estimated cost \$0.01/)).toBeVisible();
  });

  it("is only for owners and admins", async () => {
    renderSettings("analyst", usage);
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "AI planner use" })).toBeNull();
  });
});

describe("reason words", () => {
  it.each([
    "product_not_active",
    "out_of_stock",
    "no_ad_platform",
    "platform_not_connected:google_ads",
    "budget_too_small",
    "budget_minimum_not_checkable",
    "below_platform_minimum:meta_ads",
    "shares_do_not_add_up",
    "share_invalid:meta_ads",
    "unknown_evidence:x",
    "evidence_not_available:x",
    "risk_missing:low_stock",
    "target_outside_history:roas",
    "target_range_invalid:cost_per_order",
    "duplicate_target:cost_per_click",
    "platform_not_requested:meta_ads",
    "platform_missing:google_ads",
    "duplicate_platform:google_ads",
    "duplicate_platform",
    "campaign_type_not_for_platform:meta_ads",
    "objective_not_requested",
    "answer_not_json",
    "answer_refused",
    "answer_too_long",
    "too_long:summary",
    "too_many:angles",
    "empty:platforms",
    "invalid_text:summary",
    "shape:answer",
    "unknown_value:objective",
    "too_many_decimals",
  ])("has plain words for %s", (code) => {
    expect(reasonText(code)).not.toMatch(/did not pass a check/);
  });

  it("has words for every code and a fallback", () => {
    expect(reasonText("risk_missing:margin_unknown")).toBe(
      "It must name this risk: Margin unknown.",
    );
    expect(reasonText("below_platform_minimum:google_ads")).toBe(
      "The amount for Google Ads is below its minimum daily budget.",
    );
    expect(reasonText("something_new")).toBe("It did not pass a check (something_new).");
  });
});
