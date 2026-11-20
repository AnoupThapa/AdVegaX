import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import NotFound from "@/app/not-found";
import { BrandLogo } from "@/components/layout/BrandLogo";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SkipLink } from "@/components/layout/SkipLink";

import { renderWithProviders } from "../support/render";

vi.mock("next/navigation", () => import("../support/navigation"));

describe("layout components", () => {
  it("skip link targets the main landmark", () => {
    render(<SkipLink />);
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main",
    );
  });

  it("header is a banner landmark with a home link", () => {
    renderWithProviders(<SiteHeader />, { session: null });
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AdVegaX" })).toHaveAttribute("href", "/");
  });

  it("brand logo names AdVegaX once and follows the colour scheme", () => {
    const { container, unmount } = render(<BrandLogo />);
    expect(screen.getByRole("img", { name: "AdVegaX" })).toHaveAttribute(
      "src",
      "/brand/wordmark.webp",
    );
    // The mark is decorative: the wordmark carries the name.
    expect(container.querySelectorAll('img[alt=""]')).toHaveLength(1);
    expect(container.querySelectorAll('source[media="(prefers-color-scheme: dark)"]')).toHaveLength(
      2,
    );
    unmount();
    render(<BrandLogo tone="onDark" />);
    expect(screen.getByRole("img", { name: "AdVegaX" })).toHaveAttribute(
      "src",
      "/brand/wordmark-dark.webp",
    );
  });

  it("home page has a single level-one heading", () => {
    renderWithProviders(<HomePage />, { session: null });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Know what your advertising really earns",
    );
  });

  it("not-found page does not reveal whether a resource exists", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByText(/does not exist, or you do not have access/)).toBeInTheDocument();
  });
});
