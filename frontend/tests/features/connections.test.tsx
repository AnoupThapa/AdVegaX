import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CallbackLanding } from "@/features/connections/CallbackLanding";
import { ConnectionDetailPage } from "@/features/connections/ConnectionDetailPage";
import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";
import * as external from "@/lib/navigation/external";

import { click } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation, router } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

const CONN = "9a0b1c2d-3e4f-4a5b-8c6d-7e8f9a0b1c2d";
const me = testUser();
const provider = {
  code: "fake",
  display_name: "Test platform (local only)",
  category: "advertising",
  auth_scheme: "oauth2",
  capabilities: { pkce: true },
  test_only: true,
};
const connection = (extra: Record<string, unknown> = {}) => ({
  id: CONN,
  provider: "fake",
  auth_scheme: "oauth2",
  status: "active",
  authorized_by_user_id: "user-1",
  granted_scopes: ["read"],
  account_label: "Fake Business",
  last_error_code: null,
  created_at: "2026-10-12T08:00:00Z",
  revoked_at: null,
  ...extra,
});
const resource = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  connection_id: CONN,
  provider: "fake",
  kind: "ad_account",
  external_id: `ext-${id}`,
  display_name: `Account ${id}`,
  currency: "AUD",
  timezone: "Australia/Sydney",
  accessible: true,
  capabilities: {},
  linked: false,
  link_id: null,
  discovered_at: "2026-10-12T08:00:01Z",
  last_synced_at: null,
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

function baseApi(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    "GET /api/v1/auth/me": ok(me),
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    "GET /api/v1/providers": ok([provider]),
    ...extra,
  });
}

describe("Connections list", () => {
  it("shows connections with plain status, a Connections tab, and the connect section", async () => {
    baseApi("owner", {
      [`GET ${ORG_PATH}/connections`]: ok([
        connection(),
        connection({
          id: "c2",
          status: "expired",
          last_error_code: "auth_expired",
          account_label: null,
        }),
      ]),
    });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Connections" }),
    ).toBeInTheDocument();
    const tab = screen.getByRole("navigation", { name: "Organization" });
    expect(within(tab).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const link = await screen.findByRole("link", {
      name: "Test platform (local only) — Fake Business",
    });
    expect(link).toHaveAttribute("href", `/orgs/${ORG_ID}/connections/${CONN}`);
    expect(screen.getByText("Connected", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Needs reconnecting")).toBeInTheDocument();
    expect(screen.getByText(/permission has expired/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Connect Test platform (local only)" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/For testing only/)).toBeInTheDocument();
  });

  it("empty states: nothing connected, no platforms available yet", async () => {
    baseApi("owner", { [`GET ${ORG_PATH}/connections`]: ok([]), "GET /api/v1/providers": ok([]) });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    expect(await screen.findByText("Nothing is connected yet.")).toBeInTheDocument();
    expect(
      await screen.findByText(/No platforms are available to connect yet/),
    ).toBeInTheDocument();
  });

  it("analysts and viewers see connections but cannot connect", async () => {
    const api = baseApi("analyst", { [`GET ${ORG_PATH}/connections`]: ok([connection()]) });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    expect(await screen.findByRole("link", { name: /Fake Business/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Connect / })).toBeNull();
    expect(screen.getByText(/Only owners, admins and managers can connect/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/api/v1/providers")).toBe(true); // names only
  });

  it("starting a connection sends the person to the platform's https page", async () => {
    const go = vi.spyOn(external, "goToExternal").mockReturnValue(true);
    const api = baseApi("manager", {
      [`GET ${ORG_PATH}/connections`]: ok([]),
      [`POST ${ORG_PATH}/connections/fake/start`]: ok({
        authorize_url: "https://fake-platform.invalid/oauth/authorize?state=s&code_challenge=c",
        expires_in_seconds: 600,
      }),
    });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    click(await screen.findByRole("button", { name: "Connect Test platform (local only)" }));
    await waitFor(() =>
      expect(go).toHaveBeenCalledWith(
        "https://fake-platform.invalid/oauth/authorize?state=s&code_challenge=c",
      ),
    );
    expect(api.calls.find((c) => c.method === "POST")?.csrf).toBeTruthy();
  });

  it("refuses an unsafe platform address", async () => {
    const real = external.goToExternal;
    const navigate = vi.fn();
    const go = vi
      .spyOn(external, "goToExternal")
      .mockImplementation((url: string) => real(url, navigate));
    baseApi("owner", {
      [`GET ${ORG_PATH}/connections`]: ok([]),
      [`POST ${ORG_PATH}/connections/fake/start`]: ok({
        authorize_url: "javascript:alert(1)",
        expires_in_seconds: 600,
      }),
    });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    click(await screen.findByRole("button", { name: "Connect Test platform (local only)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong with the platform",
    );
    expect(go).toHaveBeenCalledWith("javascript:alert(1)");
    expect(navigate).not.toHaveBeenCalled();
  });

  it.each([
    [
      "status=connected&connection_id=x",
      "status",
      "Connected. We are now looking for the accounts",
    ],
    ["status=cancelled", "status", "Connection cancelled"],
    ["status=error&code=permission_denied", "alert", "does not allow this access"],
  ])("shows the platform's result once (%s) and cleans the address", async (search, role, text) => {
    navigation.search = search;
    baseApi("owner", { [`GET ${ORG_PATH}/connections`]: ok([]) });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
    expect(
      screen
        .getAllByRole(role as "status" | "alert")
        .some((el) => el.textContent?.includes(text.slice(0, 20))),
    ).toBe(true);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith(`/orgs/${ORG_ID}/connections`));
  });
});

describe("Callback landing (/connections)", () => {
  it("continues into the organization with only the expected details", async () => {
    navigation.search = `status=connected&organization_id=${ORG_ID}&connection_id=${CONN}&evil=<script>`;
    renderWithProviders(<CallbackLanding />);
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith(
        `/orgs/${ORG_ID}/connections?status=connected&connection_id=${CONN}`,
      ),
    );
  });

  it("explains failures that name no organization", async () => {
    navigation.search = "status=error&code=session_mismatch";
    renderWithProviders(<CallbackLanding />);
    expect(screen.getByRole("alert")).toHaveTextContent("started by a different account");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("ignores a malformed organization id", () => {
    navigation.search = "status=connected&organization_id=../../evil";
    renderWithProviders(<CallbackLanding />);
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

function detail(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  const api = baseApi(role, {
    [`GET ${ORG_PATH}/connections/${CONN}`]: ok(connection()),
    ...extra,
  });
  renderWithProviders(
    inShell(<ConnectionDetailPage />, `/orgs/${ORG_ID}/connections/${CONN}`, {
      connectionId: CONN,
    }),
    { session: me },
  );
  return api;
}

describe("Connection detail", () => {
  it("shows the connection and its accounts; missing sync time reads 'Not synced yet', never 0", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([
        resource("r1", { linked: true, link_id: "l1", last_synced_at: "2026-10-12T09:00:00Z" }),
        resource("r2", { accessible: false, currency: null, timezone: null }),
      ]),
    });
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Test platform (local only) — Fake Business",
      }),
    ).toBeInTheDocument();
    const tab = screen.getByRole("navigation", { name: "Organization" });
    expect(within(tab).getByRole("link", { name: "Connections" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const table = await screen.findByRole("table", { name: "2 accounts" });
    const [, row1, row2] = within(table).getAllByRole("row");
    expect(row1).toHaveTextContent("Linked");
    expect(within(row1!).getByRole("button", { name: "Sync Account r1 now" })).toBeInTheDocument();
    expect(row2).toHaveTextContent("Not synced yet");
    expect(row2).toHaveTextContent("No longer accessible");
    expect(row2).toHaveTextContent("Not provided");
    expect(within(row2!).queryByRole("button", { name: "Link Account r2" })).toBeNull(); // inaccessible
    expect(screen.getByText("read")).toBeInTheDocument();
  });

  it("links an account and reports it", async () => {
    let linked = false;
    const api = detail("manager", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: () => ok([resource("r1", { linked })]),
      [`POST ${ORG_PATH}/resources/r1/link`]: () => {
        linked = true;
        return ok(
          {
            id: "l1",
            resource_id: "r1",
            status: "active",
            linked_at: "2026-10-12T09:00:00Z",
            unlinked_at: null,
            unlink_reason: null,
          },
          201,
        );
      },
    });
    click(await screen.findByRole("button", { name: "Link Account r1" }));
    expect(
      await screen.findByText("Account r1 is now linked to this organization."),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Unlink Account r1" })).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual([
      `${ORG_PATH}/resources/r1/link`,
    ]);
  });

  it("syncs a linked account and follows the job to completion", async () => {
    let jobPolls = 0;
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1", { linked: true })]),
      [`POST ${ORG_PATH}/resources/r1/sync`]: ok(
        {
          id: "j1",
          job_type: "resource.sync",
          status: "queued",
          attempts: 0,
          max_attempts: 5,
          last_error_code: null,
        },
        202,
      ),
      [`GET ${ORG_PATH}/jobs/j1`]: () => {
        jobPolls += 1;
        return ok({
          id: "j1",
          job_type: "resource.sync",
          status: jobPolls > 1 ? "succeeded" : "running",
          attempts: 1,
          max_attempts: 5,
          last_error_code: null,
        });
      },
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      click(await screen.findByRole("button", { name: "Sync Account r1 now" }));
      expect(await screen.findByText("Sync: In progress")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });
      expect(await screen.findByText("Sync: Finished")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows link history with reasons", async () => {
    detail("viewer", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1")]),
      [`GET ${ORG_PATH}/resources/r1/links`]: ok([
        {
          id: "l1",
          resource_id: "r1",
          status: "unlinked",
          linked_at: "2026-10-10T09:00:00Z",
          unlinked_at: "2026-10-11T09:00:00Z",
          unlink_reason: "connection_revoked",
        },
      ]),
    });
    const toggle = await screen.findByRole("button", { name: "Show link history for Account r1" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    click(toggle);
    expect(await screen.findByText(/Connection disconnected/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Hide link history for Account r1" }),
    ).toHaveAttribute("aria-expanded", "true");
    // Viewers cannot change anything
    expect(screen.queryByRole("button", { name: /^Link |^Unlink |^Sync / })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Disconnect/ })).toBeNull();
    expect(
      screen.getByText(/Only owners, admins and managers can change connections/),
    ).toBeInTheDocument();
  });

  it("disconnects after confirmation and returns to the list", async () => {
    const api = detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1", { linked: true })]),
      [`POST ${ORG_PATH}/connections/${CONN}/disconnect`]: ok(
        connection({ status: "revoked", revoked_at: "2026-10-12T10:00:00Z" }),
      ),
      [`GET ${ORG_PATH}/connections`]: ok([]),
    });
    click(await screen.findByRole("button", { name: "Disconnect Test platform (local only)" }));
    const dialog = screen.getByRole("dialog", { name: "Disconnect Test platform (local only)?" });
    expect(api.calls.some((c) => c.path.endsWith("/disconnect"))).toBe(false);
    click(within(dialog).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith(`/orgs/${ORG_ID}/connections`));
  });

  it("asks WooCommerce merchants to revoke the key in WordPress too", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}`]: ok(connection({ provider: "woocommerce" })),
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([]),
      "GET /api/v1/providers": ok([
        { ...provider, code: "woocommerce", display_name: "WooCommerce", test_only: false },
      ]),
    });
    click(await screen.findByRole("button", { name: "Disconnect WooCommerce" }));
    const dialog = screen.getByRole("dialog", { name: "Disconnect WooCommerce?" });
    expect(within(dialog).getByText(/revoke the\s+AdVegaX key in WordPress/)).toBeInTheDocument();
  });

  it("expired connections explain what to do and offer no link/sync", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}`]: ok(
        connection({ status: "expired", last_error_code: "auth_expired" }),
      ),
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1", { linked: true })]),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("permission has expired");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: /^Sync |^Unlink / })).toBeNull();
    expect(screen.queryByRole("button", { name: "Check for new accounts" })).toBeNull();
  });

  it("while discovery runs, says it is looking for accounts", async () => {
    detail("owner", { [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([]) });
    expect(await screen.findByText(/Looking for accounts/)).toBeInTheDocument();
  });

  it("stops saying 'looking' after about a minute and offers to check again", async () => {
    let polls = 0;
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: () => {
        polls += 1;
        return ok([]);
      },
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      expect(await screen.findByText(/Looking for accounts/)).toBeInTheDocument();
      for (let i = 0; i < 25; i++) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(3100);
        });
      }
      expect(await screen.findByText(/No accounts found yet/)).toBeInTheDocument();
      expect(screen.queryByText(/Looking for accounts/)).toBeNull();
      expect(screen.getByRole("button", { name: "Check for new accounts" })).toBeEnabled();
      const settledPolls = polls;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(polls, "no more re-checks once it has given up").toBe(settledPolls);
      expect(polls).toBeLessThanOrEqual(21);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a sync whose progress cannot be read stops polling and frees the button", async () => {
    let jobPolls = 0;
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1", { linked: true })]),
      [`POST ${ORG_PATH}/resources/r1/sync`]: ok(
        {
          id: "j1",
          job_type: "resource.sync",
          status: "queued",
          attempts: 0,
          max_attempts: 5,
          last_error_code: null,
        },
        202,
      ),
      [`GET ${ORG_PATH}/jobs/j1`]: () => {
        jobPolls += 1;
        return fail(404, "NOT_FOUND");
      },
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      click(await screen.findByRole("button", { name: "Sync Account r1 now" }));
      expect(await screen.findByText(/Sync status unavailable/)).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(jobPolls).toBe(1);
      expect(screen.getByRole("button", { name: "Sync Account r1 now" })).not.toHaveAttribute(
        "aria-busy",
        "true",
      );
      expect(screen.getByRole("button", { name: "Sync Account r1 now" })).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed check for new accounts says so", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1")]),
      [`POST ${ORG_PATH}/connections/${CONN}/rediscover`]: ok(
        {
          id: "j3",
          job_type: "connection.discover",
          status: "queued",
          attempts: 0,
          max_attempts: 5,
          last_error_code: null,
        },
        202,
      ),
      [`GET ${ORG_PATH}/jobs/j3`]: ok({
        id: "j3",
        job_type: "connection.discover",
        status: "dead",
        attempts: 5,
        max_attempts: 5,
        last_error_code: "auth_expired",
      }),
    });
    await screen.findByRole("table", { name: "1 account" });
    click(screen.getByRole("button", { name: "Check for new accounts" }));
    expect(await screen.findByText(/The check for new accounts did not finish/)).toHaveTextContent(
      /reconnect/,
    );
    expect(screen.getByRole("button", { name: "Check for new accounts" })).toBeEnabled();
  });

  it("viewers are told plainly when no accounts were found", async () => {
    detail("viewer", { [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([]) });
    expect(await screen.findByText(/Looking for accounts/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check for new accounts" })).toBeNull();
  });

  it("checks for new accounts and refreshes when the job ends", async () => {
    let done = false;
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: () =>
        ok(done ? [resource("r1"), resource("r2")] : [resource("r1")]),
      [`POST ${ORG_PATH}/connections/${CONN}/rediscover`]: ok(
        {
          id: "j2",
          job_type: "connection.discover",
          status: "queued",
          attempts: 0,
          max_attempts: 5,
          last_error_code: null,
        },
        202,
      ),
      [`GET ${ORG_PATH}/jobs/j2`]: () => {
        done = true;
        return ok({
          id: "j2",
          job_type: "connection.discover",
          status: "succeeded",
          attempts: 1,
          max_attempts: 5,
          last_error_code: null,
        });
      },
    });
    await screen.findByRole("table", { name: "1 account" });
    click(screen.getByRole("button", { name: "Check for new accounts" }));
    expect(await screen.findByText("Checking the platform for accounts…")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "2 accounts" })).toBeInTheDocument();
  });

  it("not found for malformed IDs and other organizations' connections", async () => {
    baseApi("owner");
    const first = renderWithProviders(
      inShell(<ConnectionDetailPage />, `/orgs/${ORG_ID}/connections/nope`, {
        connectionId: "nope",
      }),
      { session: me },
    );
    expect(
      await screen.findByRole("heading", { name: "Connection not found" }),
    ).toBeInTheDocument();
    first.unmount();
    detail("owner", { [`GET ${ORG_PATH}/connections/${CONN}`]: fail(404, "NOT_FOUND") });
    expect(
      await screen.findByRole("heading", { name: "Connection not found" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to connections" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections`,
    );
  });

  it("explains action errors such as a connection that is no longer active", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([resource("r1")]),
      [`POST ${ORG_PATH}/resources/r1/link`]: fail(409, "CONNECTION_NOT_ACTIVE"),
    });
    click(await screen.findByRole("button", { name: "Link Account r1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not active. Reconnect");
  });
});

describe("Google Ads accounts on a connection (3-09)", () => {
  it("groups accounts under the managers they are reached through, direct ones first", async () => {
    detail("owner", {
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([
        resource("au", { group_path: "Agency > Retail clients", display_name: "Eve Zone AU" }),
        resource("nz", { group_path: "Agency > Retail clients", display_name: "Eve Zone NZ" }),
        resource("own", { group_path: null, display_name: "Own account" }),
        resource("old", {
          group_path: null,
          display_name: "Old account",
          unavailable_reason: "account_not_enabled",
        }),
      ]),
    });
    const direct = await screen.findByRole("table", { name: "Directly accessible: 2 accounts" });
    const managed = screen.getByRole("table", { name: "Through Agency › Retail clients" });
    expect(within(managed).getByText("Eve Zone AU")).toBeInTheDocument();
    expect(within(managed).getByText("Eve Zone NZ")).toBeInTheDocument();
    const tables = screen.getAllByRole("table");
    expect(tables.indexOf(direct)).toBeLessThan(tables.indexOf(managed));
    const old = within(direct).getByRole("row", { name: /Old account/ });
    expect(old).toHaveTextContent("Cannot be linked");
    expect(old).toHaveTextContent("Cancelled, suspended or closed in Google Ads");
    expect(within(old).queryByRole("button", { name: "Link Old account" })).toBeNull();
    expect(within(direct).getByRole("button", { name: "Link Own account" })).toBeInTheDocument();
  });
});

describe("Meta on the Connections pages (4-07)", () => {
  const DAY_MS = 86_400_000;
  const inDays = (days: number) => new Date(Date.now() + days * DAY_MS).toISOString();
  const meta = {
    code: "meta_ads",
    display_name: "Meta",
    category: "advertising",
    auth_scheme: "oauth2",
    capabilities: { pkce: true, token_revocation: true },
    test_only: false,
  };

  it("offers Meta as read-only and shows when each sign-in ends", async () => {
    baseApi("owner", {
      "GET /api/v1/providers": ok([meta]),
      [`GET ${ORG_PATH}/connections`]: ok([
        connection({ provider: "meta_ads", account_label: "Meta", sign_in_expires_at: inDays(40) }),
        connection({
          id: "c2",
          provider: "meta_ads",
          account_label: "Meta",
          sign_in_expires_at: inDays(3),
        }),
      ]),
    });
    renderWithProviders(inShell(<ConnectionsPage />, `/orgs/${ORG_ID}/connections`), {
      session: me,
    });
    expect(await screen.findByRole("button", { name: "Connect Meta" })).toBeInTheDocument();
    expect(screen.getByText(/only reads them — it never changes campaigns/)).toBeInTheDocument();
    expect(screen.getAllByText(/Sign-in ends/)).toHaveLength(2);
    expect(screen.getAllByText(/The Meta sign-in ends in/)).toHaveLength(1); // only the 3-day one
  });

  it("groups ad accounts by business and explains Meta's reasons", async () => {
    detail("owner", {
      "GET /api/v1/providers": ok([meta]),
      [`GET ${ORG_PATH}/connections/${CONN}`]: ok(
        connection({ provider: "meta_ads", account_label: "Meta", sign_in_expires_at: inDays(12) }),
      ),
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([
        resource("de", {
          provider: "meta_ads",
          group_path: "Eve Zone Business",
          display_name: "DE",
        }),
        resource("us", {
          provider: "meta_ads",
          group_path: "Eve Zone Business",
          display_name: "US",
          unavailable_reason: "account_unsettled",
        }),
        resource("own", { provider: "meta_ads", group_path: null, display_name: "Own" }),
      ]),
    });
    const business = await screen.findByRole("table", { name: "Business: Eve Zone Business" });
    expect(screen.getByRole("table", { name: "Not in a business: 1 account" })).toBeInTheDocument();
    const unpaid = within(business).getByRole("row", { name: /US/ });
    expect(unpaid).toHaveTextContent("Has an unpaid balance in Meta");
    expect(within(unpaid).queryByRole("button", { name: "Link US" })).toBeNull();
    expect(screen.getByText("Sign-in ends")).toBeInTheDocument();
    const notice = screen.getByText(/The Meta sign-in ends in 12 days/);
    expect(within(notice).getByRole("link", { name: "Reconnect" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/connections#connect-title`,
    );
  });

  it("explains an ended Meta sign-in", async () => {
    detail("viewer", {
      "GET /api/v1/providers": ok([meta]),
      [`GET ${ORG_PATH}/connections/${CONN}`]: ok(
        connection({
          provider: "meta_ads",
          status: "expired",
          last_error_code: "sign_in_expired",
          sign_in_expires_at: inDays(-1),
        }),
      ),
      [`GET ${ORG_PATH}/connections/${CONN}/resources`]: ok([]),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The sign-in ended (Meta sign-ins last about 60 days)",
    );
    expect(screen.queryByText("Sign-in ends")).not.toBeInTheDocument();
  });
});
