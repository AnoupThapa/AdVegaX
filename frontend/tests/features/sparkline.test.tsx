import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sparkline } from "@/components/ui/Sparkline";

describe("Sparkline", () => {
  it("draws nothing for fewer than two values", () => {
    const { container } = render(<Sparkline values={[5, null, null]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws one line for consecutive days and is hidden from assistive technology", () => {
    const { container } = render(<Sparkline values={[1, 3, 2]} />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
  });

  it("breaks the line at a missing day instead of filling it in", () => {
    const { container } = render(<Sparkline values={[1, 2, null, 4, 5]} />);
    expect(container.querySelectorAll("polyline")).toHaveLength(2);
  });
});
