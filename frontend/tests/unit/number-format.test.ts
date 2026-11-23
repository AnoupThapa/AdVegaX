import { describe, expect, it } from "vitest";

import { numberFormat } from "@/lib/format/number-format";

describe("numberFormat", () => {
  it("reuses one formatter per locale and options", () => {
    const a = numberFormat("en-AU", { style: "currency", currency: "AUD" });
    const b = numberFormat("en-AU", { style: "currency", currency: "AUD" });
    expect(a).toBe(b);
    expect(numberFormat("en-AU", { style: "currency", currency: "NZD" })).not.toBe(a);
  });

  it("formats exactly like a new Intl.NumberFormat", () => {
    const options = { style: "currency", currency: "AUD" } as const;
    expect(numberFormat("en-AU", options).format(1234.5)).toBe(
      new Intl.NumberFormat("en-AU", options).format(1234.5),
    );
    expect(numberFormat(undefined).format(1234567)).toBe(new Intl.NumberFormat().format(1234567));
  });
});
