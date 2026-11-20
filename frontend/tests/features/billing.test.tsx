import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BillingPage, money, standingText } from "@/features/billing/BillingPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";
import { KNOWN_ERROR_CODES, messageFor, ApiError } from "@/lib/api/errors";

import { click } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import {
  ORG_ID,
  ORG_PATH,
  emptyBilling,
  emptyOrganizationData,
  testOrg,
} from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const me = testUser();
const BILLING = `${ORG_PATH}/billing`;
const assign = vi.fn();
const original = window.location;

const limits = (stores: number, ads: number, members: number, ai: number, autopilot: boolean) => ({
  stores,
  ad_accounts: ads,
  members,
  ai_runs_per_day: ai,
  autopilot,
});
const PLANS = [
  {
    code: "starter",
    name: "Starter",
    currency: "aud",
    monthly: 4900,
    yearly: 49000,
    limits: limits(1, 2, 3, 10, false),
  },
  {
    code: "growth",
    name: "Growth",
    currency: "aud",
    monthly: 14900,
    yearly: 149000,
    limits: limits(3, 6, 10, 40, true),
  },
  {
    code: "scale",
    name: "Scale",
    currency: "aud",
    monthly: 39900,
    yearly: 399000,
    limits: limits(10, 20, 30, 150, true),
  },
];
const IN_TEN_DAYS = new Date(Date.now() + 10 * 86_400_000).toISOString();
const TRIAL = emptyBilling({
  enabled: true,
  status: "trialing",
  plan: PLANS[1],
  trial_ends_at: IN_TEN_DAYS,
  checkout_available: true,
  usage: { stores: 1, ad_accounts: 2, members: 2, ai_runs_today: 4 },
});
const ACTIVE = emptyBilling({
  enabled: true,
  status: "active",
  plan: PLANS[0],
  subscribed_plan: "starter",
  interval: "month",
  subscription_status: "active",
  current_period_end: "2026-11-27T00:00:00Z",
  portal_available: true,
});

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
  assign.mockReset();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...original, assign },
  });
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: original });
});

function base(role: string, billing: unknown, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    [`GET ${BILLING}`]: ok(billing),
    "GET /api/v1/billing/plans": ok(PLANS),
    ...extra,
  });
}

function render(children = <BillingPage />, path = `/orgs/${ORG_ID}/billing`) {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = path;
  renderWithProviders(<OrganizationShell>{children}</OrganizationShell>, { session: me });
}

describe("Billing", () => {
  it("shows the trial, usage against the limits and the plans; an owner chooses one", async () => {
    const api = base("owner", TRIAL, {
      [`POST ${BILLING}/checkout`]: ok({ url: "https://checkout.stripe.com/c/pay/cs_1" }),
    });
    render();
    expect(await screen.findByText(/Free trial of the Growth plan until/)).toBeVisible();
    const usage = screen.getByRole("table", { name: "Usage" });
    expect(within(usage).getByRole("row", { name: /Ad accounts 2 6/ })).toBeVisible();
    expect(within(usage).getByRole("row", { name: /AI runs today 4 40/ })).toBeVisible();
    expect(within(usage).getByRole("row", { name: /Autopilot — Yes/ })).toBeVisible();
    const plans = await screen.findByRole("list", { name: "Plans" });
    expect(plans).toHaveTextContent(money(4900, "aud"));
    expect(plans).toHaveTextContent("No autopilot");
    expect(plans).toHaveTextContent("1 store");
    click(screen.getByLabelText("Yearly (two months free)"));
    expect(plans).toHaveTextContent(money(149000, "aud"));
    click(within(plans).getByRole("button", { name: "Choose Growth" }));
    await waitFor(() =>
      expect(api.apiCalls().find((c) => c.method === "POST")?.body).toEqual({
        plan: "growth",
        interval: "year",
      }),
    );
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_1"),
    );
  });

  it("explains a refused checkout", async () => {
    base("owner", TRIAL, {
      [`POST ${BILLING}/checkout`]: fail(503, "BILLING_UNAVAILABLE", [{ reason: "price_missing" }]),
    });
    render();
    click(await screen.findByRole("button", { name: "Choose Starter" }));
    expect(
      await screen.findByText("Billing is not available right now. Try again later."),
    ).toBeVisible();
    expect(assign).not.toHaveBeenCalled();
  });

  it("says when the organization already has a plan", async () => {
    base("owner", TRIAL, { [`POST ${BILLING}/checkout`]: fail(409, "CONFLICT") });
    render();
    click(await screen.findByRole("button", { name: "Choose Scale" }));
    expect(await screen.findByText(/already has a plan or is not charged/)).toBeVisible();
  });

  it("opens Stripe's portal for a subscribed organization", async () => {
    const api = base("owner", ACTIVE, {
      [`POST ${BILLING}/portal`]: ok({ url: "https://billing.stripe.com/p/session/x" }),
    });
    render();
    expect(await screen.findByText(/Starter plan, monthly. It renews on/)).toBeVisible();
    expect(screen.queryByRole("list", { name: "Plans" })).toBeNull();
    click(screen.getByRole("button", { name: "Manage billing in Stripe" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://billing.stripe.com/p/session/x"),
    );
    expect(api.apiCalls().some((c) => c.method === "POST" && c.path === `${BILLING}/portal`)).toBe(
      true,
    );
  });

  it("explains a portal that cannot open", async () => {
    base("owner", ACTIVE, { [`POST ${BILLING}/portal`]: fail(503, "BILLING_UNAVAILABLE") });
    render();
    click(await screen.findByRole("button", { name: "Manage billing in Stripe" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Billing is not available");
  });

  it("is read-only for everyone but owners", async () => {
    base("admin", { ...TRIAL, can_manage: false, checkout_available: false });
    render();
    expect(
      await screen.findByText("Only the organization's owners can change the plan."),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /Choose/ })).toBeNull();
  });

  it("thanks the owner after Checkout until Stripe confirms", async () => {
    navigation.search = "checkout=done";
    base("owner", TRIAL);
    navigation.params = { organizationId: ORG_ID };
    navigation.pathname = `/orgs/${ORG_ID}/billing`;
    renderWithProviders(
      <OrganizationShell>
        <BillingPage />
      </OrganizationShell>,
      { session: me },
    );
    expect(await screen.findByText(/as soon as Stripe confirms the payment/)).toBeVisible();
  });

  it("says when billing is off", async () => {
    base("owner", emptyBilling());
    render();
    expect(await screen.findByText(/Billing is switched off/)).toBeVisible();
    expect(screen.queryByRole("table", { name: "Usage" })).toBeNull();
  });

  it("shows an error when the billing cannot be read", async () => {
    base("owner", TRIAL, { [`GET ${BILLING}`]: fail(500, "INTERNAL_ERROR") });
    render();
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});

describe("Billing banner", () => {
  it("warns on every page while read-only", async () => {
    base("owner", { ...TRIAL, status: "read_only", read_only: true, plan: null });
    render(<p>Reports page</p>, `/orgs/${ORG_ID}/reports`);
    const banner = await screen.findByText(/This organization is read-only/);
    expect(banner).toBeVisible();
    expect(screen.getByRole("link", { name: "Go to Billing" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/billing`,
    );
    expect(screen.getByRole("link", { name: "Billing" })).toBeVisible();
  });

  it("says when the trial ends soon, and stays quiet otherwise", async () => {
    const soon = new Date(Date.now() + 2 * 86_400_000).toISOString();
    base("owner", { ...TRIAL, trial_ends_at: soon });
    render(<p>Front page</p>, `/orgs/${ORG_ID}`);
    expect(await screen.findByText(/Free trial of the Growth plan until/)).toBeVisible();
  });

  it("is not shown during a long trial", async () => {
    const api = base("owner", TRIAL);
    render(<p>Front page</p>, `/orgs/${ORG_ID}`);
    await screen.findByText("Front page");
    await waitFor(() => expect(api.apiCalls().some((c) => c.path === BILLING)).toBe(true));
    expect(screen.queryByText(/Free trial/)).toBeNull();
  });
});

describe("Billing words", () => {
  it("describes every standing", () => {
    expect(standingText({ ...ACTIVE, status: "complimentary", plan: PLANS[2] } as never)).toBe(
      "This organization is complimentary: Scale limits, never charged.",
    );
    expect(
      standingText({
        ...ACTIVE,
        status: "past_due",
        grace_ends_at: "2026-11-03T00:00:00Z",
      } as never),
    ).toMatch(/A payment failed. Everything keeps working until/);
    expect(standingText({ ...ACTIVE, cancel_at_period_end: true } as never)).toMatch(
      /It has been cancelled and ends on/,
    );
    expect(standingText({ ...ACTIVE, interval: "year" } as never)).toMatch(/Starter plan, yearly/);
  });

  it("has messages for the new errors", () => {
    for (const code of ["PLAN_LIMIT_REACHED", "ORGANIZATION_READ_ONLY", "BILLING_UNAVAILABLE"]) {
      expect(KNOWN_ERROR_CODES).toContain(code);
    }
    expect(messageFor(new ApiError(403, "PLAN_LIMIT_REACHED"))).toMatch(/Billing page/);
  });
});
