import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Cluster, Container, Grid, Stack } from "@/components/layout/Layout";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

describe("layout primitives", () => {
  it("render the element asked for, with each variant", () => {
    const { container } = render(
      <>
        <Container as="section" size="narrow" className="extra">
          narrow
        </Container>
        <Container>default</Container>
        {([2, 3, 4, 6, 8] as const).map((gap) => (
          <Stack key={gap} gap={gap} as="ul">
            <li>stack {gap}</li>
          </Stack>
        ))}
        <Stack>stack default</Stack>
        <Cluster gap={2} spread align="start">
          c1
        </Cluster>
        <Cluster gap={4} align="end" as="nav">
          c2
        </Cluster>
        <Cluster>c3</Cluster>
        <Grid min={12}>g1</Grid>
        <Grid min={20} as="ol">
          g2
        </Grid>
        <Grid>g3</Grid>
      </>,
    );
    expect(container.querySelector("section")).toHaveTextContent("narrow");
    expect(container.querySelector("section")?.className).toContain("extra");
    expect(container.querySelectorAll("ul")).toHaveLength(5);
    expect(screen.getByRole("navigation")).toHaveTextContent("c2");
    expect(container.querySelector("ol")).toHaveTextContent("g2");
  });
});

describe("status primitives", () => {
  it("badges always carry their text, in every tone", () => {
    render(
      <>
        {(["success", "warning", "danger", "info", "neutral"] as const).map((tone) => (
          <Badge key={tone} tone={tone}>
            {tone}
          </Badge>
        ))}
        <Badge>plain</Badge>
      </>,
    );
    expect(screen.getByText("danger")).toBeInTheDocument();
    expect(screen.getByText("plain")).toBeInTheDocument();
  });

  it("skeleton lines are hidden from assistive technology at every size", () => {
    const { container } = render(
      <>
        <Skeleton size="short" />
        <Skeleton size="medium" />
        <Skeleton />
      </>,
    );
    const lines = container.querySelectorAll('[aria-hidden="true"]');
    expect(lines).toHaveLength(3);
  });
});
