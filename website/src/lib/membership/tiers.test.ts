import { describe, expect, it } from "vitest";

import {
  ANNUAL_DISCOUNT_RATE,
  annualPriceCents,
  isPatronAmountAllowed,
  PATRON_MINIMUM_MONTHLY_CENTS,
} from "./tiers";

describe("membership tier pricing", () => {
  it("uses a ten percent annual discount", () => {
    expect(ANNUAL_DISCOUNT_RATE).toBe(0.9);
    expect(annualPriceCents(1000)).toBe(10800);
    expect(annualPriceCents(2500)).toBe(27000);
    expect(annualPriceCents(5000)).toBe(54000);
    expect(annualPriceCents(7500)).toBe(81000);
    expect(annualPriceCents(10000)).toBe(108000);
  });

  it("enforces the Patron monthly minimum", () => {
    expect(PATRON_MINIMUM_MONTHLY_CENTS).toBe(5000);
    expect(isPatronAmountAllowed(4999)).toBe(false);
    expect(isPatronAmountAllowed(5000)).toBe(true);
    expect(isPatronAmountAllowed(12500)).toBe(true);
  });

  it("rounds custom annual amounts to the nearest cent", () => {
    expect(annualPriceCents(5555)).toBe(59994);
  });
});
