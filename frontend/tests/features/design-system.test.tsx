import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { Icon } from "@/components/ui/Icon";
import { Skeleton } from "@/components/ui/Skeleton";
import { Landing } from "@/features/home/Landing";
import { OrganizationNav } from "@/features/organizations/OrganizationNav";

import { click } from "../support/forms";
import { mockApi, ok } from "../support/mock-api";
import { navigation, resetNavigation } from "../support/navigation";
import { ORG_ID, ORG_PATH, testOrg } from "../support/organizations";
import { renderWithProviders, testUser } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

beforeEach(() => resetNavigation());

describe("shared components", () => {
  it("a badge always carries its status as text", () => {
    render(<Badge tone="danger">Rejected</Badge>);
    expect(screen.getByText("Rejected")).toBeVisible();
  });

  it("an empty state says what is missing and offers the next step", () => {
    render(
      <EmptyState title="No campaigns yet" action={<a href="/x">Create one</a>}>
        Campaigns appear here once an ad account is linked.
      </EmptyState>,
    );
    expect(screen.getByText("No campaigns yet")).toBeVisible();
    expect(screen.getByText(/once an ad account is linked/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Create one" })).toBeVisible();
  });

  it("icons and skeletons are decorative", () => {
    const { container } = render(
      <>
        <Icon name="overview" />
        <Skeleton size="short" />
      </>,
    );
    for (const element of container.querySelectorAll("svg, span")) {
      expect(element).toHaveAttribute("aria-hidden", "true");
    }
  });
});

describe("public home page", () => {
  it("explains the product with one h1 and real links, and invents no customers or figures", () => {
    render(<Landing />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: "Sign in" })[0]).toHaveAttribute("href", "/sign-in");
    expect(screen.getAllByRole("link", { name: "Create an account" })[0]).toHaveAttribute(
      "href",
      "/sign-up",
    );
    for (const image of screen.getAllByRole("img")) {
      expect(image).toHaveAccessibleName();
    }
    // Screenshots are of simulated data and say so.
    expect(screen.getAllByText(/simulated data/)).toHaveLength(2);
    expect(document.body.textContent).not.toMatch(/testimonial|trusted by|\d+\s?%/i);
  });
});

describe("organization navigation", () => {
  function renderNav(path: string) {
    navigation.pathname = path;
    mockApi({ [`GET ${ORG_PATH}/agency`]: ok({ agency: null, clients: [] }) });
    return renderWithProviders(<OrganizationNav org={testOrg()} />, { session: testUser() });
  }

  it("groups sections and marks the current one", () => {
    renderNav(`/orgs/${ORG_ID}/reports`);
    const nav = screen.getByRole("navigation", { name: "Organization" });
    for (const group of ["Performance", "Marketing", "Data", "Organization"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: "Reports" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("keeps a section highlighted on its sub-pages", () => {
    renderNav(`/orgs/${ORG_ID}/connections/abc`);
    expect(screen.getByRole("link", { name: "Connections" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens and closes the menu on phones, announcing its state", () => {
    renderNav(`/orgs/${ORG_ID}/stores`);
    const toggle = screen.getByRole("button", { name: /Stores/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    click(screen.getByRole("link", { name: "Members" }));
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
