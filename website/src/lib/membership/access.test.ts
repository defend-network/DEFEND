import { describe, expect, it } from "vitest";

import {
  canRegisterForEvent,
  isFreeMembershipStatus,
  isPaidMembershipStatus,
  PAID_MEMBERSHIP_STATUSES,
} from "./access";

describe("membership access status", () => {
  it("recognizes paid membership statuses", () => {
    for (const status of PAID_MEMBERSHIP_STATUSES) {
      expect(isPaidMembershipStatus(status)).toBe(true);
    }
    expect(isPaidMembershipStatus("free_access")).toBe(false);
    expect(isPaidMembershipStatus("cancelled")).toBe(false);
    expect(isPaidMembershipStatus(null)).toBe(false);
  });

  it("recognizes free access separately", () => {
    expect(isFreeMembershipStatus("free_access")).toBe(true);
    expect(isFreeMembershipStatus("active")).toBe(false);
    expect(isFreeMembershipStatus(undefined)).toBe(false);
  });

  it("allows free accounts into free public events only", () => {
    expect(
      canRegisterForEvent({ membershipStatus: "free_access", feeCents: 0 }),
    ).toBe(true);
    expect(
      canRegisterForEvent({ membershipStatus: "free_access", feeCents: 2500 }),
    ).toBe(false);
    expect(
      canRegisterForEvent({ membershipStatus: "active", feeCents: 2500 }),
    ).toBe(true);
    expect(
      canRegisterForEvent({ membershipStatus: "cancelled", feeCents: 0 }),
    ).toBe(false);
    expect(
      canRegisterForEvent({ membershipStatus: null, feeCents: 0 }),
    ).toBe(false);
  });
});
