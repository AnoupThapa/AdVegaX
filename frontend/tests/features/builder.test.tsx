import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DraftPage } from "@/features/builder/DraftPage";
import { StrategyCampaigns } from "@/features/builder/StrategyCampaigns";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { reasonText } from "@/features/changes/labels";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const DRAFT = "9a0e7c1e-0000-4000-8000-0000000000a1";
const STRATEGY = "5a0e7c1e-0000-4000-8000-0000000000b1";
const ACCOUNT = "6e2d3c4b-5f6a-4b7c-8d9e-0f1a2b3c4d5e";
const me = testUser();

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

const draft = (extra: Record<string, unknown> = {}) => ({
  id: DRAFT,
  strategy_id: STRATEGY,
  product_title: "Nitrile gloves",
  platform: "google_ads",
  ad_account_id: ACCOUNT,
  ad_account_name: "Eve Zone AU",
  creative: {
    id: "c1",
    version: 2,
    status: "approved",
    format: "google_rsa",
    angle: "Bulk savings",
    content: {
      headlines: ["Gloves in Bulk", "Order by the Box", "Fast Delivery"],
      descriptions: ["Powder-free gloves.", "Order online today."],
    },
    asset_id: null,
  },
  name: "Nitrile gloves - Search - AVX-ABC123",
  reference: "AVX-ABC123",
  daily_budget: "20.00",
  monthly_estimate: "608.00",
  currency: "AUD",
  currency_minor_units: 2,
  locations: ["AU"],
  age_min: 18,
  age_max: 65,
  keywords: [],
  landing_url: "https://shop.example/products/gloves",
  meta_page_id: null,
  meta_pixel_id: null,
  bidding: "maximize_clicks",
  declarations_confirmed: false,
  version: 1,
  status: "draft",
  created_ids: {},
  campaign_id: null,
  error_code: null,
  editable: true,
  open_action_id: null,
  created_at: "2026-10-27T01:00:00Z",
  updated_at: "2026-10-27T01:00:00Z",
  ...extra,
});

const preview = (extra: Record<string, unknown> = {}) => ({
  draft: draft(),
  passed: true,
  checks: [{ check: "creative", result: "passed", reason: null }],
  dry_run: { result: "passed", reason: null },
  budget_limits: { platform_minimum: "1.60", organization_maximum: "500.00" },
  ...extra,
});

function base(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    ...extra,
  });
}

function renderDraft() {
  navigation.params = { organizationId: ORG_ID, draftId: DRAFT };
  navigation.pathname = `/orgs/${ORG_ID}/builder/${DRAFT}`;
  renderWithProviders(
    <OrganizationShell>
      <DraftPage />
    </OrganizationShell>,
    { session: me },
  );
}

const PATH = `${ORG_PATH}/campaign-drafts/${DRAFT}`;

describe("Building a Google campaign", () => {
  it("shows the ad and saves keywords, countries, budget and the declaration", async () => {
    const api = base("manager", {
      [`GET ${PATH}`]: ok(draft()),
      [`PATCH ${PATH}`]: ok(draft({ version: 2 })),
    });
    renderDraft();
    expect(await screen.findByRole("heading", { name: /AVX-ABC123/ })).toBeVisible();
    expect(screen.getByText("Gloves in Bulk | Order by the Box | Fast Delivery")).toBeVisible();
    expect(screen.getByText(/Maximize clicks/)).toBeVisible();
    const form = screen.getByRole("form", { name: "Campaign details" });
    fill(within(form).getByLabelText("Keywords"), "nitrile gloves\n\nbulk gloves ");
    fill(within(form).getByLabelText("Match type"), "exact");
    click(within(form).getByLabelText("New Zealand"));
    fill(within(form).getByLabelText(/Daily budget/), "25.00");
    click(within(form).getByLabelText(/no EU political advertising/));
    click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "PATCH")?.body).toEqual({
        name: "Nitrile gloves - Search - AVX-ABC123",
        daily_budget: "25.00",
        locations: ["AU", "NZ"],
        landing_url: "https://shop.example/products/gloves",
        keywords: [
          { text: "nitrile gloves", match: "exact" },
          { text: "bulk gloves", match: "exact" },
        ],
        confirm_declarations: true,
        remove_pixel: false,
      }),
    );
    expect(await within(form).findByText("Saved.")).toBeVisible();
  });

  it("checks, shows the reasons, and requests the launch", async () => {
    const api = base("owner", {
      [`GET ${PATH}`]: ok(draft()),
      [`POST ${PATH}/validate`]: ok(preview()),
      [`POST ${PATH}/launch`]: ok({ id: "act-1" }, 201),
    });
    renderDraft();
    const launch = await screen.findByRole("button", { name: "Request launch" });
    expect(launch).toBeDisabled();
    click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText("AdVegaX's checks passed.")).toBeVisible();
    expect(screen.getByText(/platform minimum A\$1.60, your maximum A\$500.00/)).toBeVisible();
    click(screen.getByRole("button", { name: "Request launch" }));
    expect(
      await screen.findByText(/The launch was requested and waits for approval/),
    ).toBeVisible();
    expect(api.apiCalls().some((c) => c.path.endsWith("/launch"))).toBe(true);
  });

  it("lists what must be fixed", async () => {
    base("owner", {
      [`GET ${PATH}`]: ok(draft()),
      [`POST ${PATH}/validate`]: ok(
        preview({
          passed: false,
          checks: [
            { check: "keywords", result: "failed", reason: "keyword_duplicate:1" },
            { check: "targeting", result: "skipped", reason: null },
          ],
          dry_run: { result: "skipped", reason: null },
        }),
      ),
      [`POST ${PATH}/launch`]: fail(422, "DRAFT_INVALID", [{ reason: "keywords_required" }]),
    });
    renderDraft();
    click(await screen.findByRole("button", { name: "Check" }));
    expect(await screen.findByText(/A keyword is listed twice. \(keyword 2\)/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Request launch" })).toBeDisabled();
  });

  it("is read-only for analysts", async () => {
    base("analyst", { [`GET ${PATH}`]: ok(draft()) });
    renderDraft();
    expect(await screen.findByText("Owners, admins and managers prepare campaigns.")).toBeVisible();
    expect(screen.queryByRole("form", { name: "Campaign details" })).toBeNull();
  });
});

describe("Building a Meta campaign", () => {
  it("chooses the Page and pixel and ages", async () => {
    const api = base("owner", {
      [`GET ${PATH}`]: ok(
        draft({
          platform: "meta_ads",
          bidding: "link_clicks",
          creative: {
            ...draft().creative,
            format: "meta_single",
            content: { primary_texts: ["Reliable gloves."], headlines: ["Gloves"] },
            asset_id: "img-1",
          },
        }),
      ),
      [`GET ${ORG_PATH}/ad-accounts/${ACCOUNT}/meta-pages`]: ok([
        { id: "1122334455", name: "Eve Zone" },
      ]),
      [`GET ${ORG_PATH}/ad-accounts/${ACCOUNT}/meta-pixels`]: ok([
        { id: "5566778899", name: "Shop pixel" },
      ]),
      [`PATCH ${PATH}`]: ok(draft()),
    });
    renderDraft();
    expect(await screen.findByText("Reliable gloves.")).toBeVisible();
    const form = screen.getByRole("form", { name: "Campaign details" });
    await within(form).findByRole("option", { name: "Eve Zone" });
    fill(within(form).getByLabelText("Facebook Page the ad runs as"), "1122334455");
    await within(form).findByRole("option", { name: "Shop pixel" });
    fill(within(form).getByLabelText(/Pixel/), "5566778899");
    fill(within(form).getByLabelText("Youngest age"), "25");
    click(within(form).getByLabelText(/special ad categories/));
    click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "PATCH")?.body).toMatchObject({
        meta_page_id: "1122334455",
        meta_pixel_id: "5566778899",
        remove_pixel: false,
        age_min: 25,
        age_max: 65,
        confirm_declarations: true,
      }),
    );
  });

  it("explains when Pages cannot be read", async () => {
    base("owner", {
      [`GET ${PATH}`]: ok(draft({ platform: "meta_ads" })),
      [`GET ${ORG_PATH}/ad-accounts/${ACCOUNT}/meta-pages`]: fail(503, "SERVICE_UNAVAILABLE"),
      [`GET ${ORG_PATH}/ad-accounts/${ACCOUNT}/meta-pixels`]: ok([]),
    });
    renderDraft();
    expect(await screen.findByText(/Your Pages could not be read/)).toBeVisible();
  });
});

describe("After the launch", () => {
  it("offers Go live for a created campaign and links to it", async () => {
    const api = base("owner", {
      [`GET ${PATH}`]: ok(draft({ status: "created", editable: false, campaign_id: "camp-1" })),
      [`POST ${PATH}/go-live`]: ok({ id: "act-2" }, 201),
    });
    renderDraft();
    expect(await screen.findByRole("heading", { name: "Created — paused" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the campaign under Advertising" })).toBeVisible();
    click(screen.getByRole("button", { name: "Request Go live" }));
    expect(await screen.findByText(/Requested; it waits for approval/)).toBeVisible();
    expect(api.apiCalls().some((c) => c.path.endsWith("/go-live"))).toBe(true);
  });

  it("offers clean-up after a launch stopped part-way", async () => {
    const api = base("owner", {
      [`GET ${PATH}`]: ok(
        draft({
          status: "failed",
          editable: false,
          error_code: "incomplete",
          created_ids: { campaign: "1" },
        }),
      ),
      [`POST ${PATH}/clean-up`]: fail(409, "ACTION_DUPLICATE"),
    });
    renderDraft();
    expect(await screen.findByText(/Only part of the campaign was created/)).toBeVisible();
    click(screen.getByRole("button", { name: "Request removal of what was created" }));
    expect(await screen.findByText(/already been requested/)).toBeVisible();
    expect(api.apiCalls().some((c) => c.path.endsWith("/clean-up"))).toBe(true);
  });

  it("shows a change in progress and hides the buttons", async () => {
    base("owner", {
      [`GET ${PATH}`]: ok(draft({ status: "created", editable: false, open_action_id: "act-3" })),
    });
    renderDraft();
    expect(
      await screen.findByText(/A change of this campaign is waiting or on its way/),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request Go live" })).toBeNull();
  });

  it("finds no draft for a wrong address", async () => {
    base("owner", { [`GET ${PATH}`]: fail(404, "NOT_FOUND") });
    renderDraft();
    expect(await screen.findByRole("heading", { name: "Campaign not found" })).toBeVisible();
  });

  it("shows a failed load", async () => {
    base("owner", { [`GET ${PATH}`]: fail(500, "INTERNAL_ERROR") });
    renderDraft();
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("rejects a malformed address", async () => {
    navigation.params = { organizationId: ORG_ID, draftId: "nope" };
    navigation.pathname = `/orgs/${ORG_ID}/builder/nope`;
    base("owner");
    renderWithProviders(
      <OrganizationShell>
        <DraftPage />
      </OrganizationShell>,
      { session: me },
    );
    expect(await screen.findByRole("heading", { name: "Campaign not found" })).toBeVisible();
  });
});

describe("Campaigns on a strategy", () => {
  function renderSection(role: string, ready = true) {
    navigation.params = { organizationId: ORG_ID, strategyId: STRATEGY };
    navigation.pathname = `/orgs/${ORG_ID}/strategies/${STRATEGY}`;
    renderWithProviders(
      <OrganizationShell>
        <StrategyCampaigns
          org={testOrg({ role })}
          strategyId={STRATEGY}
          ready={ready}
          platforms={["google_ads", "meta_ads"]}
        />
      </OrganizationShell>,
      { session: me },
    );
  }

  it("lists the campaigns and builds one", async () => {
    const api = base("owner", {
      [`GET ${ORG_PATH}/campaign-drafts`]: ok([draft({ status: "live" })]),
      [`GET ${ORG_PATH}/ad-accounts`]: ok([
        {
          id: ACCOUNT,
          provider: "meta_ads",
          linked: true,
          status: "active",
          name: "Meta AU",
          external_account_id: "act_1",
        },
        {
          id: "a2",
          provider: "meta_ads",
          linked: true,
          status: "active",
          name: "Meta NZ",
          external_account_id: "act_2",
        },
      ]),
      [`POST ${ORG_PATH}/campaign-drafts`]: ok(draft({ id: "d2" }), 201),
    });
    renderSection("owner");
    expect(await screen.findByRole("link", { name: /AVX-ABC123/ })).toBeVisible();
    expect(screen.getByText(/— live/)).toBeVisible();
    fill(screen.getByLabelText("Platform"), "meta_ads");
    await screen.findByRole("option", { name: "Meta NZ" });
    fill(screen.getByLabelText("Ad account"), "a2");
    click(screen.getByRole("button", { name: "Build campaign" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "POST")?.body).toEqual({
        strategy_id: STRATEGY,
        platform: "meta_ads",
        ad_account_id: "a2",
      }),
    );
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}/builder/d2`));
  });

  it("explains a refusal, and waits for a ready strategy", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/campaign-drafts`]: ok([]),
      [`POST ${ORG_PATH}/campaign-drafts`]: fail(409, "CREATIVE_NOT_APPROVED"),
    });
    renderSection("owner");
    expect(await screen.findByText("No campaigns yet.")).toBeVisible();
    click(screen.getByRole("button", { name: "Build campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Approve a creative for this platform first.",
    );
  });

  it("uses the only account, and names a failed check", async () => {
    const api = base("owner", {
      [`GET ${ORG_PATH}/campaign-drafts`]: ok([draft({ status: "odd" as never })]),
      [`GET ${ORG_PATH}/ad-accounts`]: ok([
        {
          id: ACCOUNT,
          provider: "google_ads",
          linked: true,
          status: "active",
          name: null,
          external_account_id: "1000000001",
        },
      ]),
      [`POST ${ORG_PATH}/campaign-drafts`]: fail(422, "DRAFT_INVALID", [
        { reason: "keyword_prohibited:0" },
      ]),
    });
    renderSection("owner");
    expect(await screen.findByText(/— odd/)).toBeVisible();
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.path.endsWith("/ad-accounts"))).toBe(true),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByLabelText("Ad account")).toBeNull();
    click(screen.getByRole("button", { name: "Build campaign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/\(keyword 1\)/);
    expect(api.apiCalls().find((c) => c.method === "POST")?.body).toMatchObject({
      ad_account_id: ACCOUNT,
    });
  });

  it("shows the campaigns read-only to an analyst", async () => {
    base("analyst", { [`GET ${ORG_PATH}/campaign-drafts`]: ok([]) });
    renderSection("analyst");
    expect(await screen.findByText("No campaigns yet.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Build campaign" })).toBeNull();
  });

  it("asks for a ready strategy first", async () => {
    base("owner", { [`GET ${ORG_PATH}/campaign-drafts`]: ok([]) });
    renderSection("owner", false);
    expect(
      await screen.findByText("Mark the strategy ready and approve its creatives first."),
    ).toBeVisible();
  });
});

describe("Builder reasons", () => {
  it("names the keyword line", () => {
    expect(reasonText("keyword_prohibited:0")).toMatch(/\(keyword 1\)$/);
    expect(reasonText("landing_url_not_store")).toMatch(/Settings/);
  });
});
