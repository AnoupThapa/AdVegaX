import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AutopilotSettings, OverviewAutopilot } from "@/features/autopilot/AutopilotSettings";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import {
  ORG_ID,
  ORG_PATH,
  emptyAutopilot,
  emptyOrganizationData,
  testOrg,
} from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const me = testUser();
const AP = `${ORG_PATH}/autopilot`;
const ACCOUNT = "6e2d3c4b-5f6a-4b7c-8d9e-0f1a2b3c4d5e";
const CAMPAIGN = "8c0e7c1e-0000-4000-8000-0000000000d1";

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
});

const ready = {
  readiness: { ready: true, missing: [], verified_changes: 6, needed_changes: 5 },
};

function base(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    [`GET ${ORG_PATH}/ad-accounts`]: ok([
      {
        id: ACCOUNT,
        provider: "google_ads",
        linked: true,
        status: "active",
        name: "Eve Zone AU",
        external_account_id: "1000000001",
      },
    ]),
    [`GET ${ORG_PATH}/ad-accounts/${ACCOUNT}/campaigns`]: ok({
      items: [{ id: CAMPAIGN, name: "Gloves - Search" }],
    }),
    ...extra,
  });
}

function render(role: string) {
  navigation.params = { organizationId: ORG_ID };
  renderWithProviders(
    <OrganizationShell>
      <AutopilotSettings org={testOrg({ role })} />
      <OverviewAutopilot org={testOrg({ role })} />
    </OrganizationShell>,
    { session: me },
  );
}

describe("Settings → Autopilot", () => {
  it("is off and says what is missing", async () => {
    base("owner");
    render("owner");
    expect(await screen.findByText("Autopilot is off.")).toBeVisible();
    const missing = screen.getByRole("list", { name: "Not ready yet" });
    expect(missing).toHaveTextContent("switched off for this AdVegaX installation");
    expect(missing).toHaveTextContent("not yet among those allowed");
    expect(missing).toHaveTextContent("enough changes from recommendations");
    expect(screen.getByText(/0 of 5 needed/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Switch autopilot on" })).toBeDisabled();
  });

  it("saves what it may do, where and its limits", async () => {
    const api = base("owner", {
      [`PUT ${AP}`]: ok(emptyAutopilot({ ad_account_ids: [ACCOUNT], updated_at: "2026-10-27" })),
    });
    render("owner");
    const form = await screen.findByRole("form", { name: "Autopilot policy" });
    click(within(form).getByLabelText(/Lower the daily budget/));
    click(await within(form).findByLabelText(/Eve Zone AU/));
    click(await within(form).findByLabelText("Gloves - Search"));
    fill(within(form).getByLabelText(/Automatic changes per day/), "2");
    click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "PUT")?.body).toEqual({
        kinds: ["spend_without_results"],
        ad_account_ids: [ACCOUNT],
        excluded_campaign_ids: [CAMPAIGN],
        max_changes_per_day: 2,
        campaign_cooldown_days: 7,
        max_decrease_percent: 20,
        max_cumulative_decrease_percent: 50,
        cumulative_window_days: 30,
        min_campaign_age_days: 14,
      }),
    );
    expect(await screen.findByText("Saved.")).toBeVisible();
  });

  it("is switched on with the organization's name, and refusals are explained", async () => {
    const api = base("owner", {
      [`GET ${AP}`]: ok(emptyAutopilot({ ...ready, ad_account_ids: [ACCOUNT] })),
      [`POST ${AP}/enable`]: fail(409, "AUTOPILOT_NOT_READY", [{ reason: "no_kinds" }]),
    });
    render("owner");
    const form = await screen.findByRole("form", { name: "Switch autopilot on" });
    expect(await screen.findByText("Yes.")).toBeVisible();
    fill(within(form).getByLabelText(/Type the organization's name/), "Eve Zone");
    click(within(form).getByRole("button", { name: "Switch autopilot on" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Choose at least one kind of change.",
    );
    expect(api.apiCalls().find((c) => c.method === "POST")?.body).toEqual({ confirm: "Eve Zone" });
  });

  it("is on: says so on the Overview, a manager stops it, and shows the runs", async () => {
    const api = base("manager", {
      [`GET ${AP}`]: ok(
        emptyAutopilot({ ...ready, enabled: true, enabled_at: "2026-10-27T00:00:00Z" }),
      ),
      [`POST ${AP}/stop`]: ok(
        emptyAutopilot({ stopped_reason: "stopped", stopped_at: "2026-10-27T01:00:00Z" }),
      ),
      [`GET ${AP}/runs`]: ok([
        {
          id: "r1",
          started_at: "2026-10-27T00:00:00Z",
          considered: 2,
          made: ["a1"],
          skipped: [{ recommendation_id: "x", reason: "campaign_cooldown" }, { reason: "odd" }],
          limit_reached: false,
          stopped_reason: "change_failed",
        },
      ]),
    });
    render("manager");
    expect(await screen.findByText(/Autopilot is on since/)).toBeVisible();
    expect(screen.getByText(/AdVegaX may pause campaigns or lower budgets/)).toBeVisible();
    expect(screen.getByText("Only owners can change autopilot.")).toBeVisible();
    expect(screen.queryByRole("form", { name: "Switch autopilot on" })).toBeNull();
    const runs = await screen.findByRole("table", { name: "Recent autopilot runs" });
    expect(runs).toHaveTextContent("changed recently, odd");
    expect(runs).toHaveTextContent("could not be made");
    click(screen.getByRole("button", { name: "Stop autopilot" }));
    await waitFor(() => expect(api.apiCalls().some((c) => c.path.endsWith("/stop"))).toBe(true));
    expect(await screen.findByText(/Stopped by a person/)).toBeVisible();
  });

  it("shows why it stopped itself, an analyst cannot stop it, and errors", async () => {
    base("analyst", {
      [`GET ${AP}`]: ok(emptyAutopilot({ stopped_reason: "not_verified" })),
      [`GET ${ORG_PATH}/ad-accounts`]: ok([]),
    });
    render("analyst");
    expect(await screen.findByText(/did not show a change as it was sent/)).toBeVisible();
    expect(screen.getByText("No ad accounts linked yet.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Stop autopilot" })).toBeNull();
  });

  it("shows a failed load and a refused save", async () => {
    base("owner", { [`GET ${AP}`]: fail(500, "INTERNAL_ERROR") });
    render("owner");
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(/Something went wrong/);
  });

  it("shows a refused save", async () => {
    base("owner", { [`PUT ${AP}`]: fail(422, "VALIDATION_ERROR") });
    render("owner");
    const form = await screen.findByRole("form", { name: "Autopilot policy" });
    click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByRole("alert")).toBeVisible();
  });
});
