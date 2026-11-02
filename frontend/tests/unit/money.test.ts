import { describe, expect, it } from "vitest";

import { addDays, formatDay, todayIn } from "@/features/stores/dates";
import {
  figureReason,
  formatFigureMoney,
  formatFigureRatio,
  formatMoney,
  formatRatio,
  roundHalfEven,
} from "@/lib/format/money";

describe("roundHalfEven (display rounding only)", () => {
  it.each([
    ["2.345", 2, "2.34"],
    ["2.355", 2, "2.36"],
    ["2.3450001", 2, "2.35"],
    ["-18.905", 2, "-18.90"],
    ["-0.001", 2, "0.00"],
    ["1234.5", 0, "1234"],
    ["1235.5", 0, "1236"],
    ["1.2345", 3, "1.234"],
    ["10", 2, "10.00"],
    ["48.810000", 2, "48.81"],
    ["0.9999", 2, "1.00"],
    ["+7.125", 2, "7.12"],
  ])("%s to %i places is %s", (value, places, expected) => {
    expect(roundHalfEven(value, places)).toBe(expected);
  });

  it("rejects anything that is not a plain decimal", () => {
    for (const bad of ["", "abc", "1e5", "1,000", "NaN", "--1"]) {
      expect(roundHalfEven(bad, 2)).toBeNull();
    }
  });
});

describe("money and ratios", () => {
  it("formats in the currency with its minor units", () => {
    expect(formatMoney("1234.565", "AUD", 2, "en-AU")).toBe("$1,234.56");
    expect(formatMoney("1234.5", "JPY", 0, "en-AU").replace(/\s/g, " ")).toBe("JPY 1,234");
    expect(formatMoney("-20.79", "USD", 2, "en-US")).toBe("-$20.79");
  });

  it("never shows missing money as 0", () => {
    expect(formatMoney(null, "AUD", 2)).toBe("Not available");
    expect(formatMoney("oops", "AUD", 2)).toBe("Not available");
    expect(formatRatio(null)).toBe("Not available");
  });

  it("formats ratios as percentages", () => {
    expect(formatRatio("0.774431", "en-AU")).toBe("77.4%");
    expect(formatRatio("1", "en-AU")).toBe("100.0%");
  });

  it("explains unavailable figures in plain words", () => {
    expect(
      formatFigureMoney(
        { value: null, availability: "unavailable", reason: "missing_product_costs" },
        "AUD",
        2,
      ),
    ).toBe("Some products have no cost");
    expect(
      figureReason({
        value: null,
        availability: "unsupported",
        reason: "not_provided_by_platform",
      }),
    ).toBe("Not provided by the platform");
    expect(figureReason({ value: null, availability: "not_synchronized" })).toBe("Not synced yet");
    expect(figureReason({ value: null, availability: "unavailable", reason: "new" })).toBe(
      "Not available",
    );
    expect(formatFigureRatio({ value: "0.5", availability: "available" }, "en-AU")).toBe("50.0%");
    expect(formatFigureMoney({ value: "0", availability: "available" }, "AUD", 2, "en-AU")).toBe(
      "$0.00",
    );
  });
});

describe("store-local days", () => {
  it("uses the store's time zone for today", () => {
    const moment = new Date("2026-10-05T14:30:00Z"); // 01:30 on 6 Oct in Sydney
    expect(todayIn("Australia/Sydney", moment)).toBe("2026-10-06");
    expect(todayIn("UTC", moment)).toBe("2026-10-05");
    expect(todayIn("Not/AZone", moment)).toBe("2026-10-05");
  });

  it("adds days across month ends and formats calendar days", () => {
    expect(addDays("2026-10-01", -1)).toBe("2026-09-30");
    expect(addDays("2026-10-06", -29)).toBe("2026-09-07");
    expect(formatDay("2026-10-05", "en-AU")).toBe("5 Oct 2026");
  });
});
