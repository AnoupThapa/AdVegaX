import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CampaignPage } from "@/features/advertising/CampaignPage";
import { ChangeDetailPage, ChangesPage } from "@/features/changes/ChangesPages";
import { reasonText, statusLabel } from "@/features/changes/labels";
import { ConnectionDetailPage } from "@/features/connections/ConnectionDetailPage";
import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import {
  ORG_ID,
  ORG_PATH,
  emptyActionSettings,
  emptyOrganizationData,
  testOrg,
} from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const ACTION = "8a0e7c1e-0000-4000-8000-0000000000e1";
const CAMPAIGN = "7f3e4d5c-6a7b-4c8d-9e0f-1a2b3c4d5e6f";
const ACCOUNT = "6e2d3c4b-5f6a-4b7c-8d9e-0f1a2b3c4d5e";
const CONN = "9b0e7c1e-0000-4000-8000-0000000000f1";
const me = testUser();

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

const state = (extra: Record<string, unknown> = {}) => ({
  status: "active",
  budget_level: "campaign",
  budget_period: "daily",
  daily_budget: "50.00",
  budget_shared: false,
  ...extra,
});

const action = (extra: Record<string, unknown> = {}) => ({
  id: ACTION,
  action_type: "campaign.set_daily_budget",
  provider: "google_ads",
  campaign: {
    id: CAMPAIGN,
    name: "Gloves - Search",
    external_id: "11",
    ad_account_id: ACCOUNT,
    ad_account_name: "Eve Zone AU",
  },
  currency: "AUD",
  currency_minor_units: 2,
  params: { daily_budget: "60.00" },
  previous: state(),
  observed: null,
  status: "pending",
  checks: [
    { check: "shape", result: "passed", reason: null },
    { check: "limits", result: "passed", reason: null },
  ],
  dry_run: { result: "passed", reason: null },
  verification: null,
  error_code: null,
  platform_request: null,
  platform_answer: null,
  source: "user",
  undo_of: null,
  requested_by: "user-2",
  decided_by: null,
  decided_at: null,
  decision_reason: null,
  submitted_at: null,
  finished_at: null,
  created_at: "2026-10-26T01:00:00Z",
  updated_at: "2026-10-26T01:00:00Z",
  can_undo: false,
  events: [
    {
      from_status: null,
      status: "pending",
      actor_type: "user",
      actor_user_id: "user-2",
      detail: {},
      created_at: "2026-10-26T01:00:00Z",
    },
  ],
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

function render(ui: React.ReactElement, path: string, params: Record<string, string> = {}) {
  navigation.params = { organizationId: ORG_ID, ...params };
  navigation.pathname = path;
  renderWithProviders(<OrganizationShell>{ui}</OrganizationShell>, { session: me });
}

// ------------------------------------------------------------------ the list and one change
describe("Changes", () => {
  it("lists changes in plain words, waiting ones first", async () => {
    const api = base("viewer", { [`GET ${ORG_PATH}/actions`]: ok([action()]) });
    render(<ChangesPage />, `/orgs/${ORG_ID}/changes`);
    const link = await screen.findByRole("link", {
      name: "Daily budget from A$50.00 to A$60.00",
    });
    expect(link).toHaveAttribute("href", `/orgs/${ORG_ID}/changes/${ACTION}`);
    expect(screen.getByText("Waiting for approval")).toBeVisible();
    const listCall = api.apiCalls().find((c) => c.path === `${ORG_PATH}/actions`);
    expect(listCall?.query.get("status")).toBe("open");
  });

  it("lets an owner approve a waiting change", async () => {
    const api = base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action()),
      [`POST ${ORG_PATH}/actions/${ACTION}/approve`]: ok(action({ status: "succeeded" })),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(
      await screen.findByRole("heading", { name: "Daily budget from A$50.00 to A$60.00" }),
    ).toBeVisible();
    expect(screen.getByText(/the platform accepted the change in a test/)).toBeVisible();
    click(screen.getByRole("button", { name: "Approve and send" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/approve"))).toBe(true));
  });

  it("explains a refused approval with its reasons", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action()),
      [`POST ${ORG_PATH}/actions/${ACTION}/approve`]: fail(409, "SECOND_PERSON_REQUIRED"),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    click(await screen.findByRole("button", { name: "Approve and send" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone other than the person who asked must approve this change.",
    );
  });

  it("asks a manager to wait for an owner or admin", async () => {
    base("manager", { [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action()) });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(
      await screen.findByText("An owner or admin approves or rejects this change."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve and send" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel this change" })).toBeVisible();
  });

  it("needs a reason to reject", async () => {
    const api = base("admin", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action()),
      [`POST ${ORG_PATH}/actions/${ACTION}/reject`]: ok(action({ status: "rejected" })),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    click(await screen.findByRole("button", { name: "Reject" }));
    const form = screen.getByRole("form", { name: "Reject the change" });
    const submit = within(form).getByRole("button", { name: "Reject" });
    expect(submit).toBeDisabled();
    fill(within(form).getByLabelText(/Why is it rejected/), "Not during the sale");
    click(submit);
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.path.endsWith("/reject"))?.body).toEqual({
        reason: "Not during the sale",
      }),
    );
  });

  it("shows what was sent, the verification and the history; offers undo", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(
        action({
          status: "succeeded",
          verification: "verified",
          observed: state({ daily_budget: "60.00" }),
          platform_request: { method: "campaignBudgets:mutate", validateOnly: false },
          submitted_at: "2026-10-26T01:05:00Z",
          can_undo: true,
          events: [
            ...action().events,
            {
              from_status: "submitting",
              status: "succeeded",
              actor_type: "worker",
              actor_user_id: null,
              detail: {},
              created_at: "2026-10-26T01:05:00Z",
            },
          ],
        }),
      ),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByText("Checked: the platform shows the change.")).toBeVisible();
    expect(screen.getByText(/campaignBudgets:mutate/)).toBeVisible();
    expect(screen.getByText(/by AdVegaX/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Undo this change" })).toBeVisible();
  });

  it("says why a change was not made", async () => {
    base("viewer", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(
        action({ status: "stale", error_code: "campaign_changed" }),
      ),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The campaign changed on the platform after this was requested",
    );
  });
});

// ------------------------------------------------------------------ on a campaign
const figures = {
  availability: "available",
  reason: null,
  impressions: 0,
  clicks: 0,
  cost: "0",
  conversions: "0",
  conversion_value: "0",
  click_through_rate: { value: null, availability: "unavailable", reason: "no_impressions" },
  cost_per_click: { value: null, availability: "unavailable", reason: "no_clicks" },
  cost_per_conversion: { value: null, availability: "unavailable", reason: "no_conversions" },
  conversion_value_per_cost: { value: null, availability: "unavailable", reason: "no_cost" },
};
const campaignDetail = (extra: Record<string, unknown> = {}) => ({
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
    shared: false,
  },
  figures,
  provider: "google_ads",
  source: "platform_reported",
  synced_from: "2025-09-14",
  currency: "AUD",
  currency_minor_units: 2,
  from_day: "2026-09-15",
  to_day: "2026-10-14",
  ad_groups: [],
  ...extra,
});
const preview = (extra: Record<string, unknown> = {}) => ({
  action_type: "campaign.pause",
  campaign_id: CAMPAIGN,
  currency: "AUD",
  currency_minor_units: 2,
  passed: true,
  checks: [{ check: "state", result: "passed", reason: null }],
  dry_run: { result: "passed", reason: null },
  current: state(),
  budget_limits: null,
  ...extra,
});

function campaignPage(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
  const api = base(role, {
    [`GET ${ORG_PATH}/campaigns/${CAMPAIGN}`]: ok(campaignDetail()),
    ...extra,
  });
  render(<CampaignPage />, `/orgs/${ORG_ID}/advertising/campaigns/${CAMPAIGN}`, {
    campaignId: CAMPAIGN,
  });
  return api;
}

describe("Changes on a campaign", () => {
  it("checks a pause with the platform's test, then requests it", async () => {
    const api = campaignPage("manager", {
      [`POST ${ORG_PATH}/actions/validate`]: ok(preview()),
      [`POST ${ORG_PATH}/actions`]: ok(action({ action_type: "campaign.pause", params: {} }), 201),
    });
    click(await screen.findByRole("button", { name: "Pause" }));
    expect(await screen.findByText("AdVegaX's checks passed.")).toBeVisible();
    click(screen.getByRole("button", { name: "Request this change" }));
    expect(
      await screen.findByText(/The change was requested and waits for approval/),
    ).toBeVisible();
    const sent = api
      .apiCalls()
      .find((c) => c.method === "POST" && c.path === `${ORG_PATH}/actions`);
    expect(sent?.body).toEqual({
      action_type: "campaign.pause",
      campaign_id: CAMPAIGN,
      params: {},
    });
  });

  it("shows the allowed budget range and blocks a change that fails a check", async () => {
    const api = campaignPage("owner", {
      [`POST ${ORG_PATH}/actions/validate`]: ok(
        preview({
          action_type: "campaign.set_daily_budget",
          passed: false,
          checks: [{ check: "limits", result: "failed", reason: "increase_too_large" }],
          dry_run: { result: "skipped", reason: null },
          budget_limits: {
            lowest: "5.00",
            highest: "75.00",
            platform_minimum: "1.60",
            organization_maximum: "500.00",
            increase_percent: 50,
            decrease_percent: 90,
          },
        }),
      ),
    });
    click(await screen.findByRole("button", { name: "Change budget" }));
    fill(screen.getByLabelText(/New daily budget/), "80");
    click(screen.getByRole("button", { name: "Check" }));
    expect(
      await screen.findByText(/One change may set between A\$5.00 and A\$75.00 a day/),
    ).toBeVisible();
    expect(
      screen.getByText("That raises the budget by more than one change allows."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Request this change" })).toBeDisabled();
    const checked = api.apiCalls().find((c) => c.path.endsWith("/actions/validate"));
    expect(checked?.body).toEqual({
      action_type: "campaign.set_daily_budget",
      campaign_id: CAMPAIGN,
      params: { daily_budget: "80" },
    });
  });

  it("explains when changes are not allowed for the connection", async () => {
    campaignPage("owner", {
      [`POST ${ORG_PATH}/actions/validate`]: fail(409, "ACTION_NOT_ALLOWED", [
        { reason: "changes_not_allowed" },
      ]),
    });
    click(await screen.findByRole("button", { name: "Pause" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Changes are not allowed for this connection yet.",
    );
  });

  it("shows a change in progress instead of the buttons", async () => {
    campaignPage("owner", { [`GET ${ORG_PATH}/actions`]: ok([action({ status: "queued" })]) });
    expect(await screen.findByText(/A change of this campaign is in progress/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("offers nothing to analysts and viewers", async () => {
    campaignPage("analyst");
    expect(
      await screen.findByText("Owners, admins and managers can request changes."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Change budget" })).toBeNull();
  });
});

// ------------------------------------------------------------------ settings and access
describe("Change settings", () => {
  it("saves the pause switch, the second-person rule and the maximum", async () => {
    const api = base("owner", {
      [`PUT ${ORG_PATH}/action-settings`]: ok(emptyActionSettings({ max_daily_budget: "500.00" })),
    });
    render(<OrganizationSettings />, `/orgs/${ORG_ID}/settings`);
    const form = await screen.findByRole("form", { name: "Change settings" });
    expect(form).toHaveTextContent("budget changes are refused until you choose one");
    click(within(form).getByLabelText(/Require a second person/));
    fill(within(form).getByLabelText(/Maximum daily budget per campaign/), "500.00");
    click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "PUT")?.body).toEqual({
        paused: false,
        require_second_person: true,
        max_daily_budget: "500.00",
        landing_domains: [],
      }),
    );
  });

  it("says when changes are off for the installation, read-only for managers", async () => {
    base("manager", {
      [`GET ${ORG_PATH}/action-settings`]: ok(emptyActionSettings({ engine_enabled: false })),
    });
    render(<OrganizationSettings />, `/orgs/${ORG_ID}/settings`);
    expect(
      await screen.findByText(/Changes are switched off for this AdVegaX installation/),
    ).toBeVisible();
    expect(screen.getByText("Only owners and admins can change these settings.")).toBeVisible();
  });
});

const connection = (extra: Record<string, unknown> = {}) => ({
  id: CONN,
  provider: "meta_ads",
  auth_scheme: "oauth2",
  status: "active",
  authorized_by_user_id: "user-1",
  granted_scopes: ["ads_read"],
  account_label: "Meta",
  last_error_code: null,
  created_at: "2026-10-12T08:00:00Z",
  revoked_at: null,
  ...extra,
});
const access = (extra: Record<string, unknown> = {}) => ({
  connection_id: CONN,
  provider: "meta_ads",
  supported: true,
  allowed: false,
  allowed_at: null,
  allowed_by: null,
  missing_permissions: [],
  can_request_permission: false,
  ...extra,
});

function connectionPage(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
  const api = base(role, {
    "GET /api/v1/providers": ok([]),
    [`GET ${ORG_PATH}/connections/${CONN}`]: ok(connection()),
    [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([]),
    ...extra,
  });
  render(<ConnectionDetailPage />, `/orgs/${ORG_ID}/connections/${CONN}`, {
    connectionId: CONN,
  });
  return api;
}

describe("Changes through a connection", () => {
  it("lets an owner allow changes", async () => {
    const api = connectionPage("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(access()),
      [`PUT ${ORG_PATH}/connections/${CONN}/write-access`]: ok(access({ allowed: true })),
    });
    click(await screen.findByRole("button", { name: "Allow changes" }));
    expect(await screen.findByRole("button", { name: "Stop allowing changes" })).toBeVisible();
    expect(api.apiCalls().find((c) => c.method === "PUT")?.body).toEqual({ allowed: true });
  });

  it("asks Meta for the change permission by signing in again", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const api = connectionPage("admin", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(
        access({ missing_permissions: ["ads_management"], can_request_permission: true }),
      ),
      [`POST ${ORG_PATH}/connections/meta_ads/start`]: ok({
        authorize_url: "https://www.facebook.com/v26.0/dialog/oauth?config_id=2",
        expires_in_seconds: 600,
      }),
    });
    click(await screen.findByRole("button", { name: "Sign in again to allow changes" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith(
        "https://www.facebook.com/v26.0/dialog/oauth?config_id=2",
      ),
    );
    expect(api.apiCalls().find((c) => c.path.endsWith("/start"))?.body).toEqual({
      params: { access: "changes" },
    });
    vi.unstubAllGlobals();
  });

  it("is read-only for managers", async () => {
    connectionPage("manager", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(access()),
    });
    expect(
      await screen.findByText("Owners and admins decide whether changes are allowed."),
    ).toBeVisible();
  });
});

describe("Change labels", () => {
  it("has words for every status and a fallback for a platform's own code", () => {
    for (const s of ["pending", "queued", "submitting", "unknown", "succeeded", "failed", "stale"])
      expect(statusLabel(s).label).not.toBe(s);
    expect(reasonText("budget_on_ad_sets")).toMatch(/ad sets/);
    expect(reasonText("campaign_error_x")).toBe(
      "The platform refused the change (campaign error x).",
    );
    expect(reasonText(null)).toBe("");
  });
});

// ------------------------------------------------------------------ more cases
describe("Changes — more cases", () => {
  it("says when nothing waits, and when a filter has nothing", async () => {
    base("owner");
    render(<ChangesPage />, `/orgs/${ORG_ID}/changes`);
    expect(
      await screen.findByText("No changes are waiting. Request one from a campaign's page."),
    ).toBeVisible();
    fill(screen.getByLabelText("Show"), "succeeded");
    expect(await screen.findByText("No changes here yet.")).toBeVisible();
  });

  it("marks undos and Meta changes in the list, and shows a failed load", async () => {
    const api = base("owner", {
      [`GET ${ORG_PATH}/actions`]: ok([
        action({
          id: "a2",
          action_type: "campaign.resume",
          provider: "meta_ads",
          undo_of: ACTION,
          params: {},
          campaign: { ...action().campaign, ad_account_name: null },
        }),
      ]),
    });
    render(<ChangesPage />, `/orgs/${ORG_ID}/changes`);
    expect(await screen.findByRole("link", { name: "Resume the campaign" })).toBeVisible();
    expect(screen.getByText("(undo)")).toBeVisible();
    expect(screen.getByText("Meta")).toBeVisible();
    api.set(`GET ${ORG_PATH}/actions`, fail(500, "INTERNAL_ERROR"));
    fill(screen.getByLabelText("Show"), "failed");
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("finds no change for an unknown or malformed address", async () => {
    base("owner", { [`GET ${ORG_PATH}/actions/${ACTION}`]: fail(404, "NOT_FOUND") });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByRole("heading", { name: "Change not found" })).toBeVisible();
  });

  it("rejects a malformed id without asking the API", async () => {
    const api = base("owner");
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/nope`, { actionId: "nope" });
    expect(await screen.findByRole("heading", { name: "Change not found" })).toBeVisible();
    expect(api.apiCalls().some((c) => c.path.includes("/actions/"))).toBe(false);
  });

  it("shows a failed load of one change", async () => {
    base("owner", { [`GET ${ORG_PATH}/actions/${ACTION}`]: fail(500, "INTERNAL_ERROR") });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("shows a rejection with its reason and nothing more to do", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(
        action({
          status: "rejected",
          decided_at: "2026-10-26T02:00:00Z",
          decision_reason: "Not during the sale",
          checks: [{ check: "limits", result: "failed", reason: "daily_limit_reached" }],
          dry_run: { result: "failed", reason: "invalid_request" },
        }),
      ),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByText(/“Not during the sale”/)).toBeVisible();
    expect(
      screen.getByText("This ad account has reached today's number of changes."),
    ).toBeVisible();
    expect(screen.getByText("The platform refused the change.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "What next" })).toBeNull();
  });

  it("follows an unknown outcome and a mismatch in plain words", async () => {
    base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(
        action({
          action_type: "campaign.pause",
          params: {},
          status: "unknown",
          error_code: "outcome_unknown",
          verification: "mismatch",
          previous: state({ daily_budget: null, budget_level: "ad_group", status: "paused" }),
          observed: state({ status: null }),
          undo_of: "8a0e7c1e-0000-4000-8000-0000000000e0",
          submitted_at: "2026-10-26T01:05:00Z",
          events: [
            {
              from_status: "submitting",
              status: "unknown",
              actor_type: "worker",
              actor_user_id: null,
              detail: { reason: "outcome_unknown" },
              created_at: "2026-10-26T01:05:00Z",
            },
          ],
        }),
      ),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findAllByText(/AdVegaX is checking the campaign/)).toHaveLength(2);
    expect(screen.getByText(/does not show the change as requested/)).toBeVisible();
    expect(screen.getByText(/budget on the ad sets/)).toBeVisible();
    expect(screen.getByText(/Status not known/)).toBeVisible();
    expect(screen.getByRole("link", { name: "the earlier change" })).toBeVisible();
  });

  it("requests an undo and links to it", async () => {
    const api = base("manager", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(
        action({ status: "succeeded", can_undo: true, verification: "not_checked" }),
      ),
      [`POST ${ORG_PATH}/actions/${ACTION}/undo`]: ok(action({ id: "u1" }), 201),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    expect(await screen.findByText(/could not read the campaign back/)).toBeVisible();
    click(screen.getByRole("button", { name: "Undo this change" }));
    expect(await screen.findByText("The undo was requested and waits for approval.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/changes/u1`,
    );
    expect(api.apiCalls().some((c) => c.path.endsWith("/undo"))).toBe(true);
  });

  it("cancels, and shows a refused cancel with its reasons", async () => {
    const api = base("owner", {
      [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action({ status: "queued" })),
      [`POST ${ORG_PATH}/actions/${ACTION}/cancel`]: fail(409, "ACTION_INVALID", [
        { check: "limits", reason: "budget_changed_recently" },
      ]),
    });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    click(await screen.findByRole("button", { name: "Cancel this change" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This campaign's budget was changed less than an hour ago.");
    expect(api.apiCalls().some((c) => c.path.endsWith("/cancel"))).toBe(true);
  });

  it("lets an approver change their mind about rejecting", async () => {
    base("owner", { [`GET ${ORG_PATH}/actions/${ACTION}`]: ok(action()) });
    render(<ChangeDetailPage />, `/orgs/${ORG_ID}/changes/${ACTION}`, { actionId: ACTION });
    click(await screen.findByRole("button", { name: "Reject" }));
    click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByRole("form", { name: "Reject the change" })).toBeNull();
  });
});

describe("Changes on a campaign — more cases", () => {
  it("resumes a paused campaign and shows a refused request", async () => {
    campaignPage("owner", {
      [`GET ${ORG_PATH}/campaigns/${CAMPAIGN}`]: ok(campaignDetail({ status: "paused" })),
      [`POST ${ORG_PATH}/actions/validate`]: ok(
        preview({
          action_type: "campaign.resume",
          current: state({ status: "paused", daily_budget: null }),
        }),
      ),
      [`POST ${ORG_PATH}/actions`]: fail(409, "ACTION_DUPLICATE"),
    });
    click(await screen.findByRole("button", { name: "Resume" }));
    expect(await screen.findByText("Now: paused")).toBeVisible();
    click(screen.getByRole("button", { name: "Request this change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This change has already been requested for this campaign.",
    );
    click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Request this change" })).toBeNull();
  });

  it("offers no change for a removed campaign", async () => {
    campaignPage("owner", {
      [`GET ${ORG_PATH}/campaigns/${CAMPAIGN}`]: ok(campaignDetail({ status: "removed" })),
    });
    expect(await screen.findByRole("heading", { name: "Changes" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Change budget" })).toBeNull();
  });
});

describe("Change settings and access — more cases", () => {
  it("shows a failed load and a refused save", async () => {
    base("owner", {
      [`PUT ${ORG_PATH}/action-settings`]: fail(422, "ACTION_INVALID", [
        { check: "shape", reason: "max_daily_budget_precision" },
      ]),
      [`GET ${ORG_PATH}/action-settings`]: ok(
        emptyActionSettings({
          paused: true,
          max_daily_budget: "500.00",
          updated_at: "2026-10-26T01:00:00Z",
        }),
      ),
    });
    render(<OrganizationSettings />, `/orgs/${ORG_ID}/settings`);
    const form = await screen.findByRole("form", { name: "Change settings" });
    expect(within(form).getByLabelText(/Pause all changes/)).toBeChecked();
    expect(form).toHaveTextContent("Now A$500.00");
    fill(within(form).getByLabelText(/Maximum daily budget/), "");
    click(within(form).getByLabelText(/Pause all changes/));
    click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "The maximum has more decimals than the currency allows.",
    );
  });

  it("shows when the settings cannot be read", async () => {
    base("owner", { [`GET ${ORG_PATH}/action-settings`]: fail(500, "INTERNAL_ERROR") });
    render(<OrganizationSettings />, `/orgs/${ORG_ID}/settings`);
    await waitFor(() =>
      expect(
        screen.getAllByRole("alert").some((a) => /Something went wrong/.test(a.textContent ?? "")),
      ).toBe(true),
    );
  });

  it("stops allowing changes, and explains a missing permission it cannot request", async () => {
    const api = connectionPage("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(access({ allowed: true })),
      [`PUT ${ORG_PATH}/connections/${CONN}/write-access`]: fail(409, "ACTION_NOT_ALLOWED", [
        { reason: "permission_missing" },
      ]),
    });
    expect(await screen.findByText(/Allowed: AdVegaX may pause, resume/)).toBeVisible();
    click(screen.getByRole("button", { name: "Stop allowing changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign in again and allow changes.");
    api.set(
      `GET ${ORG_PATH}/connections/${CONN}/write-access`,
      ok(access({ missing_permissions: ["ads_management"] })),
    );
  });

  it("explains a missing permission at the platform", async () => {
    connectionPage("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(
        access({ missing_permissions: ["ads_management"] }),
      ),
    });
    expect(
      await screen.findByText(/The platform has not given AdVegaX permission to make changes/),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Allow changes" })).toBeNull();
  });

  it("refuses an unsafe sign-in address", async () => {
    connectionPage("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(
        access({ missing_permissions: ["ads_management"], can_request_permission: true }),
      ),
      [`POST ${ORG_PATH}/connections/meta_ads/start`]: ok({
        authorize_url: "javascript:alert(1)",
        expires_in_seconds: 600,
      }),
    });
    click(await screen.findByRole("button", { name: "Sign in again to allow changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The platform's sign-in address could not be opened.",
    );
  });

  it("shows nothing for a platform AdVegaX cannot change", async () => {
    connectionPage("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/write-access`]: ok(access({ supported: false })),
    });
    expect(await screen.findByRole("heading", { name: /Meta/ })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Changes through this connection" })).toBeNull();
  });
});

describe("Change descriptions", () => {
  it("describes a budget without a previous amount, and pauses", async () => {
    const { describe: words } = await import("@/features/changes/labels");
    const money = (v: string) => `$${v}`;
    expect(words(action({ previous: state({ daily_budget: null }) }) as never, money)).toBe(
      "Daily budget to $60.00",
    );
    expect(words(action({ action_type: "campaign.pause" }) as never, money)).toBe(
      "Pause the campaign",
    );
    expect(statusLabel("something_new")).toEqual({ label: "something_new", tone: "warn" });
  });
});
