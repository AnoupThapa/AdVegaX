import { afterEach, describe, expect, it, vi } from "vitest";

import {
  forgetInvitationToken,
  pendingInvitationToken,
  rememberInvitationToken,
} from "@/features/organizations/invitation-token";
import {
  browserTimeZone,
  currencyOptions,
  formatDateTime,
  isOrganizationId,
  nameErrors,
  requiredChoice,
  timeZoneOptions,
} from "@/features/organizations/options";
import {
  ROLES,
  assignableRoles,
  canAssign,
  canManageMember,
  canManageMembers,
  canUpdateOrganization,
  isRole,
  roleLabel,
} from "@/features/organizations/permissions";

afterEach(() => vi.restoreAllMocks());

describe("organization roles mirror the API matrix (API §24)", () => {
  it.each([
    ["owner", true],
    ["admin", true],
    ["manager", false],
    ["analyst", false],
    ["viewer", false],
    ["unknown", false],
  ])("%s manages members: %s", (role, expected) => {
    expect(canManageMembers(role)).toBe(expected);
    expect(canUpdateOrganization(role)).toBe(expected);
  });

  it("only owners grant the owner role; nobody assigns above their own", () => {
    expect(canAssign("owner", "owner")).toBe(true);
    expect(canAssign("admin", "owner")).toBe(false);
    expect(canAssign("admin", "admin")).toBe(true);
    expect(canAssign("manager", "admin")).toBe(false);
    expect(canAssign("viewer", "viewer")).toBe(true);
    expect(canAssign("ghost", "viewer")).toBe(false);
    expect(canAssign("owner", "ghost")).toBe(false);
  });

  it("lists assignable roles per actor", () => {
    expect(assignableRoles("owner")).toEqual([...ROLES]);
    expect(assignableRoles("admin")).toEqual(["admin", "manager", "analyst", "viewer"]);
    expect(assignableRoles("manager")).toEqual([]);
  });

  it("admins cannot change or remove owners", () => {
    expect(canManageMember("admin", "owner")).toBe(false);
    expect(canManageMember("admin", "manager")).toBe(true);
    expect(canManageMember("owner", "owner")).toBe(true);
    expect(canManageMember("manager", "viewer")).toBe(false);
  });

  it("labels roles, passing unknown values through", () => {
    expect(isRole("analyst")).toBe(true);
    expect(roleLabel("analyst")).toBe("Analyst");
    expect(roleLabel("auditor")).toBe("auditor");
  });
});

describe("organization options and checks", () => {
  it("accepts only UUIDs as organization IDs", () => {
    expect(isOrganizationId("0b6f3f0e-1f2a-4c1e-9a55-3f1f0d1f2a3b")).toBe(true);
    expect(isOrganizationId("not-a-uuid")).toBe(false);
    expect(isOrganizationId("../admin")).toBe(false);
  });

  it("offers ISO currencies with names, keeping a saved code", () => {
    const options = currencyOptions("XYZ");
    expect(options.find((o) => o.value === "AUD")?.label).toMatch(/^AUD — /);
    expect(options.some((o) => o.value === "XYZ")).toBe(true);
  });

  it("falls back to codes when names are unavailable", () => {
    vi.spyOn(Intl, "DisplayNames").mockImplementation(() => {
      throw new Error("unsupported");
    });
    expect(currencyOptions().find((o) => o.value === "NPR")?.label).toBe("NPR");
  });

  it("offers time zones, keeping a saved alias", () => {
    const zones = timeZoneOptions("Asia/Katmandu");
    expect(zones.some((z) => z.value === "Australia/Sydney")).toBe(true);
    expect(zones.find((z) => z.value === "Asia/Katmandu")).toBeDefined();
    expect(zones.find((z) => z.value === "America/New_York")?.label).toBe("America/New York");
  });

  it("copes with a browser that cannot list values", () => {
    vi.spyOn(Intl, "supportedValuesOf").mockImplementation(() => {
      throw new RangeError("unsupported");
    });
    expect(currencyOptions()).toEqual([]);
    expect(timeZoneOptions("UTC")).toEqual([{ value: "UTC", label: "UTC" }]);
  });

  it("reads the browser time zone, or nothing", () => {
    expect(browserTimeZone()).not.toBe("");
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new Error("broken");
    });
    expect(browserTimeZone()).toBe("");
  });

  it("checks names and required choices", () => {
    expect(nameErrors("  ")).toEqual(["Enter a name for the organization."]);
    expect(nameErrors("x".repeat(121))).toEqual(["Use at most 120 characters."]);
    expect(nameErrors("Eve Zone")).toEqual([]);
    expect(requiredChoice("", "Choose one.")).toEqual(["Choose one."]);
    expect(requiredChoice("AUD", "Choose one.")).toEqual([]);
  });

  it("formats API dates and shows unreadable ones unchanged", () => {
    expect(formatDateTime("2026-10-08T06:00:00Z")).toMatch(/2026/);
    expect(formatDateTime("soon")).toBe("soon");
  });
});

describe("invitation token memory", () => {
  it("is held in memory only and can be forgotten", () => {
    forgetInvitationToken();
    expect(pendingInvitationToken()).toBeNull();
    rememberInvitationToken("inv_abcdefghijklmnop");
    expect(pendingInvitationToken()).toBe("inv_abcdefghijklmnop");
    forgetInvitationToken();
    expect(pendingInvitationToken()).toBeNull();
  });
});
