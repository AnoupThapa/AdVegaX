import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreativeSetPage, CreativesPage } from "@/features/creatives/CreativesPages";
import { checkText, creativeReasonText, fieldLabel } from "@/features/creatives/labels";
import { OrganizationSettings } from "@/features/organizations/OrganizationSettings";
import { OrganizationShell } from "@/features/organizations/OrganizationShell";
import { clearCsrfToken } from "@/lib/api/csrf";

import { click, fill } from "../support/forms";
import { fail, mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, emptyOrganizationData, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => {
  resetNavigation();
  clearCsrfToken();
  vi.stubGlobal(
    "URL",
    Object.assign(URL, { createObjectURL: () => "blob:img", revokeObjectURL: () => {} }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const SET = "6a0e7c1e-0000-4000-8000-0000000000c1";
const STRATEGY = "5a0e7c1e-0000-4000-8000-0000000000b1";
const ASSET = "7a0e7c1e-0000-4000-8000-0000000000d1";

const version = (id: string, n: number, status = "draft") => ({
  id,
  version: n,
  status,
  created_at: "2026-10-26T01:00:00Z",
});

const creative = (extra: Record<string, unknown> = {}) => ({
  id: "c-google",
  set_id: SET,
  strategy_id: STRATEGY,
  product_id: "p-1",
  product_title: "Nitrile gloves",
  concept_id: "k-google",
  version: 1,
  latest: true,
  platform: "google_ads",
  format: "google_rsa",
  angle: "Bulk savings",
  status: "draft",
  content: {
    headlines: ["Nitrile Gloves in Bulk", "Boxes of 100 for $50.00", "Fast Delivery"],
    descriptions: ["Powder-free gloves for clinics.", "Order online today."],
    path1: "gloves",
    path2: "nitrile",
  },
  rationale: "Buyers search for bulk boxes.",
  compliance_notes: ["Check the delivery promise."],
  checks: [],
  approvable: true,
  asset: null,
  decided_by: null,
  decided_at: null,
  decision_reason: null,
  created_by: "user-1",
  created_at: "2026-10-26T01:00:00Z",
  versions: [version("c-google", 1)],
  ...extra,
});

const meta = (extra: Record<string, unknown> = {}) =>
  creative({
    id: "c-meta",
    concept_id: "k-meta",
    platform: "meta_ads",
    format: "meta_single",
    angle: "Busy kitchens",
    content: {
      primary_texts: ["Reliable gloves for busy kitchens."],
      headlines: ["Bulk nitrile gloves"],
      descriptions: ["Free delivery"],
      call_to_action: "SHOP_NOW",
    },
    compliance_notes: [],
    versions: [version("c-meta", 1)],
    ...extra,
  });

const set = (creatives = [creative(), meta()]) => ({
  id: SET,
  strategy_id: STRATEGY,
  product_id: "p-1",
  product_title: "Nitrile gloves",
  created_at: "2026-10-26T01:00:00Z",
  ai_run_id: "run-1",
  creatives,
});

const asset = {
  id: ASSET,
  content_type: "image/png",
  width: 800,
  height: 800,
  bytes: 1234,
  sha256: "a".repeat(64),
  original_name: "gloves.png",
  status: "active",
  uploaded_by: "user-1",
  created_at: "2026-10-26T01:00:00Z",
};

function routes(role = "owner", extra: Parameters<typeof mockApi>[0] = {}) {
  return {
    [`GET ${ORG_PATH}`]: ok(testOrg({ role })),
    ...emptyOrganizationData(),
    [`GET ${ORG_PATH}/creative-sets/${SET}`]: ok(set()),
    [`GET ${ORG_PATH}/creative-sets`]: ok([
      {
        id: SET,
        strategy_id: STRATEGY,
        product_title: "Nitrile gloves",
        created_at: "2026-10-26T01:00:00Z",
        concepts: 2,
        approved: 0,
      },
    ]),
    [`GET ${ORG_PATH}/creative-assets`]: ok([asset]),
    [`GET ${ORG_PATH}/creative-assets/${ASSET}/content`]: () =>
      new Response(new Blob(["png"], { type: "image/png" }), {
        status: 200,
        headers: { "content-type": "image/png" },
      }),
    ...extra,
  };
}

function renderSet() {
  navigation.params = { organizationId: ORG_ID, setId: SET };
  navigation.pathname = `/orgs/${ORG_ID}/creatives/${SET}`;
  return renderWithProviders(
    <OrganizationShell>
      <CreativeSetPage />
    </OrganizationShell>,
    { session: testUser() },
  );
}

function renderIndex() {
  navigation.params = { organizationId: ORG_ID };
  navigation.pathname = `/orgs/${ORG_ID}/creatives`;
  return renderWithProviders(
    <OrganizationShell>
      <CreativesPage />
    </OrganizationShell>,
    { session: testUser() },
  );
}

const card = async (name: RegExp) =>
  (await screen.findByRole("heading", { name })).closest("li") as HTMLElement;

describe("A creative set", () => {
  it("previews each platform's ad with its checks and notes", async () => {
    mockApi(routes());
    renderSet();
    expect(
      await screen.findByRole("heading", { name: "Creatives for Nitrile gloves" }),
    ).toBeVisible();
    const google = await card(/Google Ads: Bulk savings/);
    const preview = within(google).getByLabelText("Google Ads preview");
    expect(preview).toHaveTextContent(
      "Nitrile Gloves in Bulk | Boxes of 100 for $50.00 | Fast Delivery",
    );
    expect(preview).toHaveTextContent("your-store › gloves › nitrile");
    expect(google).toHaveTextContent("Passes every AdVegaX check.");
    expect(google).toHaveTextContent("Check the delivery promise.");
    expect(google).toHaveTextContent("Draft · version 1 of 1");
    const metaCard = await card(/Meta: Busy kitchens/);
    expect(within(metaCard).getByLabelText("Meta preview")).toHaveTextContent("Shop now");
    expect(metaCard).toHaveTextContent("No image chosen yet.");
  });

  it("explains what must be fixed and blocks approval", async () => {
    mockApi(
      routes("manager", {
        [`GET ${ORG_PATH}/creative-sets/${SET}`]: ok(
          set([
            creative({
              approvable: false,
              checks: [
                { code: "too_long", field: "headlines[2]", detail: "30", severity: "block" },
                {
                  code: "prohibited_term",
                  field: "descriptions[0]",
                  detail: "cure",
                  severity: "block",
                },
              ],
            }),
          ]),
        ),
      }),
    );
    renderSet();
    const google = await card(/Google Ads: Bulk savings/);
    expect(google).toHaveTextContent("To fix: Headline 3 is longer than 30 characters.");
    expect(google).toHaveTextContent('To fix: Description 1 uses a prohibited claim: "cure".');
    expect(within(google).getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("approves after the flagged wording is confirmed", async () => {
    const api = mockApi(
      routes("owner", {
        [`GET ${ORG_PATH}/creative-sets/${SET}`]: ok(
          set([
            creative({
              checks: [
                { code: "superlative", field: "headlines[0]", detail: "best", severity: "flag" },
              ],
            }),
          ]),
        ),
        [`POST ${ORG_PATH}/creatives/c-google/approve`]: ok(creative({ status: "approved" })),
      }),
    );
    renderSet();
    const google = await card(/Google Ads: Bulk savings/);
    expect(google).toHaveTextContent('To check: Headline 1 makes a superlative claim ("best")');
    const approve = within(google).getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    click(within(google).getByRole("checkbox", { name: "I have checked the flagged wording" }));
    click(approve);
    await waitFor(() =>
      expect(api.calls.find((c) => c.path.endsWith("/approve"))?.body).toEqual({
        confirm_flags: true,
      }),
    );
  });

  it("shows the checks that failed at approval", async () => {
    mockApi(
      routes("owner", {
        [`POST ${ORG_PATH}/creatives/c-google/approve`]: fail(422, "CREATIVE_CHECKS_FAILED", [
          {
            reason: "price_not_in_catalogue",
            field: "headlines[1]",
            detail: "39.95",
            severity: "block",
          },
        ]),
      }),
    );
    renderSet();
    const google = await card(/Google Ads: Bulk savings/);
    click(within(google).getByRole("button", { name: "Approve" }));
    const alert = await within(google).findByRole("alert");
    expect(alert).toHaveTextContent("This creative does not pass AdVegaX's checks yet.");
    expect(alert).toHaveTextContent(
      "Headline 2 states a price (39.95) that is not one of the product's prices.",
    );
  });

  it("rejects with a reason", async () => {
    const api = mockApi(
      routes("admin", {
        [`POST ${ORG_PATH}/creatives/c-meta/reject`]: ok(meta({ status: "rejected" })),
      }),
    );
    renderSet();
    const metaCard = await card(/Meta: Busy kitchens/);
    click(within(metaCard).getByRole("button", { name: "Reject" }));
    const submit = within(metaCard).getByRole("button", { name: "Reject this version" });
    expect(submit).toBeDisabled();
    fill(within(metaCard).getByLabelText("Why is it rejected?"), "Too generic.");
    click(submit);
    await waitFor(() =>
      expect(api.calls.find((c) => c.path.endsWith("/reject"))?.body).toEqual({
        reason: "Too generic.",
      }),
    );
  });

  it("edits as a new version, one line per line, with an image for Meta", async () => {
    const api = mockApi(
      routes("analyst", {
        [`PATCH ${ORG_PATH}/creatives/c-meta`]: ok(meta({ version: 2 })),
        [`PATCH ${ORG_PATH}/creatives/c-google`]: ok(creative({ version: 2 })),
      }),
    );
    renderSet();
    const metaCard = await card(/Meta: Busy kitchens/);
    expect(within(metaCard).queryByRole("button", { name: "Approve" })).toBeNull(); // analysts draft
    click(within(metaCard).getByRole("button", { name: "Edit" }));
    fill(within(metaCard).getByLabelText("Headlines"), "Bulk gloves\n\n  Gloves for cafes ");
    fill(within(metaCard).getByLabelText("Call to action"), "ORDER_NOW");
    await within(metaCard).findByRole("option", { name: /gloves\.png/ });
    fill(within(metaCard).getByLabelText("Image"), ASSET);
    click(within(metaCard).getByRole("button", { name: "Save as a new version" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = api.calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({
      content: {
        primary_texts: ["Reliable gloves for busy kitchens."],
        headlines: ["Bulk gloves", "Gloves for cafes"],
        descriptions: ["Free delivery"],
        call_to_action: "ORDER_NOW",
      },
      asset_id: ASSET,
      remove_asset: false,
    });
    const google = await card(/Google Ads: Bulk savings/);
    click(within(google).getByRole("button", { name: "Edit" }));
    fill(within(google).getByLabelText(/^Display path 2/), " bulk ");
    click(within(google).getByRole("button", { name: "Save as a new version" }));
    await waitFor(() =>
      expect(
        (
          api.calls.filter((c) => c.method === "PATCH").at(-1)?.body as {
            content: { path2: string };
          }
        ).content.path2,
      ).toBe("bulk"),
    );
  });

  it("shows the image of a Meta creative and a rejection reason", async () => {
    mockApi(
      routes("viewer", {
        [`GET ${ORG_PATH}/creative-sets/${SET}`]: ok(
          set([
            meta({
              asset: { id: ASSET, content_type: "image/png", width: 800, height: 800 },
              status: "rejected",
              decision_reason: "Too generic.",
              decided_at: "2026-10-26T02:00:00Z",
            }),
          ]),
        ),
      }),
    );
    renderSet();
    const metaCard = await card(/Meta: Busy kitchens/);
    expect(await within(metaCard).findByRole("img", { name: "The ad's image" })).toHaveAttribute(
      "src",
      "blob:img",
    );
    expect(metaCard).toHaveTextContent("Why it was rejected: Too generic.");
    expect(within(metaCard).queryByRole("button", { name: "Edit" })).toBeNull(); // viewers read
  });

  it("treats unknown sets as not found", async () => {
    mockApi(routes("owner", { [`GET ${ORG_PATH}/creative-sets/${SET}`]: fail(404, "NOT_FOUND") }));
    renderSet();
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});

describe("Creatives page and images", () => {
  it("lists drafted sets and the image library", async () => {
    mockApi(routes());
    renderIndex();
    expect(await screen.findByRole("link", { name: "Nitrile gloves" })).toHaveAttribute(
      "href",
      `/orgs/${ORG_ID}/creatives/${SET}`,
    );
    expect(screen.getByText(/0 of 2 approved/)).toBeVisible();
    const library = await screen.findByRole("list", { name: "Images" });
    expect(await within(library).findByRole("img", { name: "gloves.png" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Creatives" })).toHaveAttribute("aria-current", "page");
  });

  it("uploads an image and explains a refusal", async () => {
    const api = mockApi(
      routes("owner", {
        [`POST ${ORG_PATH}/creative-assets`]: fail(422, "ASSET_INVALID", [{ reason: "too_small" }]),
      }),
    );
    renderIndex();
    const input = await screen.findByLabelText("Add an image");
    const file = new File(["x"], "tiny.png", { type: "image/png" });
    Object.defineProperty(input, "files", { value: [file] });
    fill(input, "");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This file is not an image AdVegaX can use.");
    expect(alert).toHaveTextContent("The picture is too small: at least 600 × 600 pixels.");
    expect(api.calls.some((c) => c.method === "POST" && c.path.endsWith("/creative-assets"))).toBe(
      true,
    );
  });

  it("archives an image", async () => {
    const api = mockApi(
      routes("owner", {
        [`POST ${ORG_PATH}/creative-assets/${ASSET}/archive`]: ok({ ...asset, status: "archived" }),
      }),
    );
    renderIndex();
    click(await screen.findByRole("button", { name: "Archive gloves.png" }));
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith("/archive"))).toBe(true));
  });

  it("lets viewers look without uploading", async () => {
    mockApi(
      routes("viewer", {
        [`GET ${ORG_PATH}/creative-sets`]: ok([]),
        [`GET ${ORG_PATH}/creative-assets`]: ok([]),
      }),
    );
    renderIndex();
    expect(await screen.findByText("No creatives yet.")).toBeVisible();
    expect(await screen.findByText("No images yet.")).toBeVisible();
    expect(screen.queryByLabelText("Add an image")).toBeNull();
  });
});

describe("Creative rules in Settings", () => {
  function renderSettings(role: string, extra: Parameters<typeof mockApi>[0] = {}) {
    const api = mockApi({ ...routes(role), ...extra });
    navigation.params = { organizationId: ORG_ID };
    navigation.pathname = `/orgs/${ORG_ID}/settings`;
    renderWithProviders(
      <OrganizationShell>
        <OrganizationSettings />
      </OrganizationShell>,
      { session: testUser() },
    );
    return api;
  }

  it("saves the organization's own words", async () => {
    const api = renderSettings("owner", {
      [`PUT ${ORG_PATH}/creative-rules`]: ok({
        prohibited_terms: ["hospital grade"],
        allowed_caps: ["EVE"],
        base_prohibited_terms: ["cure"],
        updated_at: "2026-10-26T03:00:00Z",
      }),
    });
    expect(await screen.findByRole("heading", { name: "Creative rules" })).toBeVisible();
    expect(
      screen.getByText(/3 terms, such as “cure”, “100% effective”, “tga approved”/),
    ).toBeVisible();
    fill(screen.getByLabelText("Your prohibited words or phrases"), "hospital grade\n");
    fill(screen.getByLabelText("Words you may write in capitals"), "eve");
    click(screen.getByRole("button", { name: "Save creative rules" }));
    expect(await screen.findByText("Creative rules saved.")).toBeVisible();
    expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({
      prohibited_terms: ["hospital grade"],
      allowed_caps: ["eve"],
    });
  });

  it("is read-only below admin", async () => {
    renderSettings("manager");
    expect(await screen.findByText("Owners and admins can change these.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save creative rules" })).toBeNull();
  });
});

describe("words", () => {
  it.each([
    ["too_long", "headlines[0]", "30", "Headline 1 is longer than 30 characters."],
    [
      "phone_number",
      "descriptions[1]",
      null,
      "Description 2 contains a phone number (not allowed in Google Ads text).",
    ],
    ["all_caps", "primary_texts[0]", "HUGE", "Primary text 1 has a word in capitals (HUGE)"],
    ["unknown_value", "call_to_action", null, "Call to action is not one of the allowed choices."],
    ["something_new", "path1", null, "Display path 1 did not pass a check (something_new)."],
  ])("%s on %s", (code, field, detail, expected) => {
    expect(checkText({ code, field, detail })).toContain(expected);
  });

  it("reads the planner's reasons", () => {
    expect(creativeReasonText("google_ads[0].too_long:headlines[2]=30")).toBe(
      "Google Ads concept 1: Headline 3 is longer than 30 characters.",
    );
    expect(creativeReasonText("meta_ads[1].prohibited_term:primary_texts[0]=cure")).toBe(
      'Meta concept 2: Primary text 1 uses a prohibited claim: "cure".',
    );
    expect(creativeReasonText("shape:answer")).toBeNull();
    expect(fieldLabel("content")).toBe("The ad");
  });
});
