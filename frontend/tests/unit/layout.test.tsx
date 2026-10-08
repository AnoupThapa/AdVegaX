import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "@/app/page";
import NotFound from "@/app/not-found";
import { SiteHeader } from "@/components/layout/SiteHeader";
import { SkipLink } from "@/components/layout/SkipLink";

describe("layout components", () => {
  it("skip link targets the main landmark", () => {
    render(<SkipLink />);
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main",
    );
  });

  it("header is a banner landmark with a home link", () => {
    render(<SiteHeader />);
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AdVegaX" })).toHaveAttribute("href", "/");
  });

  it("home page has a single level-one heading", () => {
    render(<HomePage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("region", { name: "AdVegaX" })).toBeInTheDocument();
  });

  it("not-found page does not reveal whether a resource exists", () => {
    render(<NotFound />);
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByText(/does not exist, or you do not have access/)).toBeInTheDocument();
  });
});
