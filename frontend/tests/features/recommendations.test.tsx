import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { OptimizationSettings } from "@/features/recommendations/OptimizationSettings";
import {
  CampaignRecommendations,
  OverviewRecommendations,
  RecommendationDetailPage,
  RecommendationsPage,
} from "@/features/recommendations/RecommendationsPages";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const REC = "7b0e7c1e-0000-4000-8000-0000000000c1";
const CAMPAIGN = "8c0e7c1e-0000-4000-8000-0000000000d1";
const me = testUser();
const LIST = `${ORG_PATH}/recommendations`;
const ONE = `${LIST}/${REC}`;

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

const rec = (extra: Record<string, unknown> = {}) => ({
  id: REC,
  kind: "spend_without_results",
  status: "open",
  campaign: {
    id: CAMPAIGN,
    name: "Gloves - Search",
    provider: "google_ads",
    ad_account_id: "a1",
    ad_account_name: "Eve Zone AU",
  },
  funnel: null,
  figures: { spend: "AUD 140.00", conversions: "0" },
  raw_figures: { "recent.spend": "140" },
  periods: {
    from: "2026-10-07",
    to: "2026-10-13",
    baseline_from: "2026-09-09",
    baseline_to: "2026-10-06",
  },
  currency: "AUD",
  proposal: {
    action_type: "campaign.pause",
    params: {},
    currency: "AUD",
    previous_daily_budget: null,
    text: "Pause the campaign",
  },
  note: null,
  prechecks: [{ check: "state", result: "passed", reason: null }],
  ready: true,
  explanation: "In the last 7 days this campaign spent AUD 140.00 with no conversions.",
  confidence: "medium",
  assumptions: ["Tracking works."],
  risks: ["Pausing stops all traffic."],
  rank: 1,
  explained_by: "rules",
  ai_run_id: null,
  expires_at: "2026-10-17T00:00:00Z",
  closed_reason: null,
  decided_by: null,
  decided_at: null,
  decision_reason: null,
  decision_note: null,
  action: null,
  outcomes: [],
  created_at: "2026-10-14T00:00:00Z",
  ...extra,
});

const list = (items: unknown[], summary: Record<string, unknown> = {}) => ({
  summary: {
    enabled: true,
    open: items.length,
    last_run: {
      ran_at: "2026-10-14T00:00:00Z",
      campaigns_checked: 2,
      found: items.length,
      profit_rules: "skipped",
      profit_reason: "costs_missing",
      explained_by: "rules",
      ai_problem: "ai_unavailable",
    },
    refreshes_left: 2,
    ...summary,
  },
  items,
});

function base(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    ...extra,
  });
}

function render(node: React.ReactNode, params: Record<string, string> = {}) {
  navigation.params = { organizationId: ORG_ID, ...params };
  navigation.pathname = `/orgs/${ORG_ID}/recommendations`;
  renderWithProviders(<OrganizationShell>{node}</OrganizationShell>, { session: me });
}

describe("The recommendations page", () => {
  it("lists the advice with the last look and looks again", async () => {
    const api = base("manager", {
      [`GET ${LIST}`]: ok(list([rec()])),
      [`POST ${LIST}/refresh`]: ok(list([rec()], { refreshes_left: 1 })),
    });
    render(<RecommendationsPage />);
    const items = await screen.findByRole("list", { name: "Recommendations" });
    expect(within(items).getByRole("link", { name: "Spend without results" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/recommendations/${REC}`,
    );
    expect(items).toHaveTextContent("Gloves - Search · Google Ads · Medium confidence");
    expect(items).toHaveTextContent("Rules only");
    expect(items).toHaveTextContent("Proposed: Pause the campaign");
    expect(screen.getByText(/product costs are missing for too many sales/)).toBeVisible();
    expect(screen.getByText(/the AI is not set up/)).toBeVisible();
    click(screen.getByRole("button", { name: "Look again now" }));
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.method === "POST" && c.path.endsWith("/refresh"))).toBe(
        true,
      ),
    );
    fill(screen.getByLabelText("Show"), "decided");
    await waitFor(() =>
      expect(api.apiCalls().some((c) => c.query.get("status") === "decided")).toBe(true),
    );
  });

  it("says when there is nothing, when switched off, and shows a refresh refusal", async () => {
    base("owner", {
      [`GET ${LIST}`]: ok(list([], { enabled: true, last_run: null, refreshes_left: 1 })),
      [`POST ${LIST}/refresh`]: fail(429, "REFRESH_LIMIT"),
    });
    render(<RecommendationsPage />);
    expect(await screen.findByText("Nothing needs your attention right now.")).toBeVisible();
    expect(screen.getByText(/has not looked at your campaigns yet/)).toBeVisible();
    click(screen.getByRole("button", { name: "Look again now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/as often as allowed today/);
  });

  it("is read-only for an analyst and says when recommendations are off", async () => {
    base("analyst", {
      [`GET ${LIST}`]: ok(list([], { enabled: false })),
    });
    render(<RecommendationsPage />);
    expect(await screen.findByText(/switched off for this AdVegaX installation/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Look again now" })).toBeNull();
  });

  it("shows a failed load", async () => {
    base("owner", { [`GET ${LIST}`]: fail(500, "INTERNAL_ERROR") });
    render(<RecommendationsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  });
});

describe("A recommendation", () => {
  it("shows the figures, checks, assumptions and risks, and an owner approves it", async () => {
    const api = base("owner", {
      [`GET ${ONE}`]: ok(rec()),
      [`POST ${ONE}/approve`]: ok(
        rec({
          status: "approved",
          action: { id: "act1", status: "succeeded", verification: "verified" },
        }),
      ),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Spend without results" }),
    ).toBeVisible();
    const figures = screen.getByLabelText("The figures behind it");
    expect(figures).toHaveTextContent("SpendAUD 140.00");
    expect(screen.getByText("Tracking works.")).toBeVisible();
    expect(screen.getByText("Pausing stops all traffic.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open the campaign" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/advertising/campaigns/${CAMPAIGN}`,
    );
    click(screen.getByRole("button", { name: "Approve and send" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/approve"))).toBe(true));
  });

  it("explains an out-of-date refusal and lets a manager request instead", async () => {
    base("manager", {
      [`GET ${ONE}`]: ok(rec()),
      [`POST ${ONE}/approve`]: fail(409, "RECOMMENDATION_OUT_OF_DATE", [
        { reason: "campaign_changed" },
      ]),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    click(await screen.findByRole("button", { name: "Request this change" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This advice is out of date");
    expect(alert).toHaveTextContent("The campaign's status or budget changed since this advice.");
  });

  it("is rejected with a reason and a note", async () => {
    const api = base("owner", {
      [`GET ${ONE}`]: ok(rec()),
      [`POST ${ONE}/reject`]: ok(rec({ status: "rejected", decision_reason: "wrong_time" })),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    click(await screen.findByRole("button", { name: "Reject" }));
    const form = screen.getByRole("form", { name: "Reject this advice" });
    expect(within(form).getByRole("button", { name: "Reject this advice" })).toBeDisabled();
    fill(within(form).getByLabelText("Why is it rejected?"), "wrong_time");
    fill(within(form).getByLabelText("Note (optional)"), "Sale next week");
    click(within(form).getByRole("button", { name: "Reject this advice" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("/reject"))?.body).toEqual({
        reason: "wrong_time",
        note: "Sale next week",
      }),
    );
    click(within(form).getByRole("button", { name: "Cancel" }));
  });

  it("marks information as looked into, with the reason no change is proposed", async () => {
    const api = base("owner", {
      [`GET ${ONE}`]: ok(
        rec({
          kind: "losing_money",
          proposal: {
            action_type: null,
            params: {},
            currency: null,
            previous_daily_budget: null,
            text: "No change: look into it",
          },
          note: "budget_shared",
          prechecks: [],
          ready: false,
          explained_by: "ai",
          confidence: "low",
        }),
      ),
      [`POST ${ONE}/done`]: ok(rec({ status: "done" })),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByText("Its budget is shared with other campaigns.")).toBeVisible();
    expect(screen.getByText(/Explained by AI/)).toBeVisible();
    click(screen.getByRole("button", { name: "Mark as looked into" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/done"))).toBe(true));
  });

  it("shows a decided recommendation, its change and what happened since", async () => {
    base("analyst", {
      [`GET ${ONE}`]: ok(
        rec({
          status: "rejected",
          decided_at: "2026-10-15T00:00:00Z",
          decision_reason: "wrong_time",
          decision_note: "Sale next week",
          action: { id: "act1", status: "succeeded", verification: "verified" },
          outcomes: [
            {
              after_days: 7,
              before: { figures: { spend: { value: "140" } } },
              after: { figures: {} },
              created_at: "2026-10-22T00:00:00Z",
            },
          ],
        }),
      ),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByText(/Not now/)).toBeVisible();
    expect(screen.getByText("“Sale next week”")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/changes/act1`,
    );
    const table = screen.getByRole("table", { name: "7 days before and after" });
    expect(within(table).getByRole("row", { name: /Spend/ })).toHaveTextContent(
      "Spend140Not available",
    );
  });

  it("is read-only for an analyst while open, and shows a closed reason", async () => {
    base("analyst", { [`GET ${ONE}`]: ok(rec()) });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByText("Owners, admins and managers decide on advice.")).toBeVisible();
  });

  it("names the funnel for a drop-off, and the out-of-date reason", async () => {
    base("owner", {
      [`GET ${ONE}`]: ok(
        rec({
          kind: "funnel_drop",
          campaign: null,
          funnel: { view: "platform", platform: "meta_ads" },
          status: "out_of_date",
          closed_reason: "no_longer_true",
        }),
      ),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByText(/Meta's own funnel/)).toBeVisible();
    expect(screen.getByText("With the latest figures, the rule no longer applies.")).toBeVisible();
  });

  it("is not found, fails to load, or has a malformed id", async () => {
    base("owner", { [`GET ${ONE}`]: fail(404, "NOT_FOUND") });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByRole("heading", { name: "Recommendation not found" })).toBeVisible();
  });

  it("refuses a malformed id and shows load errors", async () => {
    base("owner", { [`GET ${ONE}`]: fail(500, "INTERNAL_ERROR") });
    render(<RecommendationDetailPage />, { recommendationId: "nope" });
    expect(await screen.findByRole("heading", { name: "Recommendation not found" })).toBeVisible();
  });

  it("shows a failed load", async () => {
    base("owner", { [`GET ${ONE}`]: fail(500, "INTERNAL_ERROR") });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  });
});

describe("Plain words for every case", () => {
  it("names unknown kinds and statuses, Meta, both funnels and closed advice", async () => {
    base("owner", {
      [`GET ${LIST}`]: ok(
        list(
          [
            rec({ kind: "new_kind", status: "approved", explained_by: "ai" }),
            rec({
              id: "r2",
              status: "odd",
              campaign: {
                id: CAMPAIGN,
                name: "Meta Sales",
                provider: "meta_ads",
                ad_account_id: "a2",
                ad_account_name: null,
              },
            }),
            rec({ id: "r3", kind: "funnel_drop", campaign: null, funnel: { view: "whole" } }),
            rec({
              id: "r4",
              kind: "funnel_drop",
              campaign: null,
              funnel: { view: "platform", platform: "google_ads" },
            }),
          ],
          {
            refreshes_left: 0,
            last_run: {
              ran_at: "2026-10-14T00:00:00Z",
              campaigns_checked: 1,
              found: 4,
              profit_rules: "skipped",
              profit_reason: "mystery",
              explained_by: "rules",
              ai_problem: "mystery",
            },
          },
        ),
      ),
    });
    render(<RecommendationsPage />);
    const items = await screen.findByRole("list", { name: "Recommendations" });
    expect(items).toHaveTextContent("new_kind");
    expect(items).toHaveTextContent("Explained by AI");
    expect(items).toHaveTextContent("Meta Sales · Meta");
    expect(items).toHaveTextContent("odd");
    expect(items).toHaveTextContent("Your business's funnel");
    expect(items).toHaveTextContent("Google Ads's own funnel");
    expect(screen.getByText(/your gross margin is not known/)).toBeVisible();
    expect(screen.getByText(/the AI was not used/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Look again now" })).toBeDisabled();
  });

  it("shows advice explained by the AI without a summary note, and a budget proposal", async () => {
    base("owner", {
      [`GET ${ONE}`]: ok(
        rec({
          kind: "budget_limited",
          note: "mystery_note",
          ready: false,
          figures: {},
          assumptions: [],
          risks: [],
          prechecks: [{ check: "limits", result: "failed", reason: "maximum_not_set" }],
          proposal: {
            action_type: "campaign.set_daily_budget",
            params: { daily_budget: "60.00" },
            currency: "AUD",
            previous_daily_budget: "50.00",
            text: "Raise the daily budget from AUD 50.00 to AUD 60.00",
          },
        }),
      ),
    });
    render(<RecommendationDetailPage />, { recommendationId: REC });
    expect(await screen.findByText("mystery_note")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve and send" })).toBeDisabled();
    expect(screen.getByText("Before it can be approved, see the checks above.")).toBeVisible();
    expect(screen.queryByLabelText("The figures behind it")).toBeNull();
  });
});

describe("Elsewhere", () => {
  it("counts open advice on the Overview and lists a campaign's", async () => {
    const api = base("owner", { [`GET ${LIST}`]: ok(list([rec(), rec({ id: "x2" })])) });
    render(
      <>
        <OverviewRecommendations org={testOrg({ role: "owner" })} />
        <CampaignRecommendations campaignId={CAMPAIGN} />
      </>,
    );
    expect(await screen.findByText("2 pieces of advice wait for your decision.")).toBeVisible();
    expect(
      await screen.findByRole("list", { name: "Open recommendations for this campaign" }),
    ).toHaveTextContent("Spend without results — Pause the campaign");
    expect(api.apiCalls().some((c) => c.query.get("campaign_id") === CAMPAIGN)).toBe(true);
  });

  it("says one or none on the Overview", async () => {
    base("owner", { [`GET ${LIST}`]: ok(list([rec()])) });
    render(<OverviewRecommendations org={testOrg({ role: "owner" })} />);
    expect(await screen.findByText("1 piece of advice waits for your decision.")).toBeVisible();
  });

  it("saves the thresholds; read-only for a manager", async () => {
    const api = base("owner", {
      [`PUT ${ORG_PATH}/optimization-settings`]: ok({
        enabled: false,
        currency: "AUD",
        min_spend: "100.00",
        min_conversions: 5,
        budget_step_percent: 10,
        cost_jump_percent: 30,
        max_step_percent: 50,
        updated_at: "2026-10-14T00:00:00Z",
      }),
    });
    render(<OptimizationSettings org={testOrg({ role: "owner" })} />);
    const form = await screen.findByRole("form", { name: "Recommendation settings" });
    fill(within(form).getByLabelText(/Least spend in the last 7 days/), "100");
    fill(within(form).getByLabelText(/Budget step/), "10");
    click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "PUT")?.body).toEqual({
        min_spend: "100",
        min_conversions: 5,
        budget_step_percent: 10,
        cost_jump_percent: 30,
      }),
    );
    expect(await screen.findByText(/switched off for this AdVegaX installation/)).toBeVisible();
  });

  it("shows a refused save", async () => {
    base("owner", {
      [`PUT ${ORG_PATH}/optimization-settings`]: fail(422, "VALIDATION_ERROR"),
    });
    render(<OptimizationSettings org={testOrg({ role: "owner" })} />);
    const form = await screen.findByRole("form", { name: "Recommendation settings" });
    click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toBeVisible();
  });

  it("shows settings errors and read-only settings", async () => {
    base("manager", {
      [`PUT ${ORG_PATH}/optimization-settings`]: fail(422, "VALIDATION_ERROR"),
    });
    render(<OptimizationSettings org={testOrg({ role: "manager" })} />);
    expect(
      await screen.findByText("Only owners and admins can change these settings."),
    ).toBeVisible();
  });

  it("shows a failed settings load and a refused save", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/optimization-settings`]: fail(500, "INTERNAL_ERROR"),
    });
    render(<OptimizationSettings org={testOrg({ role: "owner" })} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
  });
});
