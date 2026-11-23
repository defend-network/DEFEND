import { describe, expect, it } from "vitest";

import {
  memberHasEntitlement,
  tierAllowsEntitlement,
} from "./entitlements";

describe("membership entitlements", () => {
  it("limits free accounts to announcements and eligible public events", () => {
    expect(tierAllowsEntitlement("free", "announcements")).toBe(true);
    expect(tierAllowsEntitlement("free", "public_events")).toBe(true);
    expect(tierAllowsEntitlement("free", "workshops")).toBe(false);
    expect(tierAllowsEntitlement("free", "gym")).toBe(false);
    expect(tierAllowsEntitlement("free", "volunteering")).toBe(false);
    expect(tierAllowsEntitlement("free", "directory")).toBe(false);
  });

  it("grants standard access to workshops, gym, volunteering, and directory", () => {
    expect(tierAllowsEntitlement("standard", "workshops")).toBe(true);
    expect(tierAllowsEntitlement("standard", "gym")).toBe(true);
    expect(tierAllowsEntitlement("standard", "volunteering")).toBe(true);
    expect(tierAllowsEntitlement("standard", "directory")).toBe(true);
    expect(tierAllowsEntitlement("standard", "supporter_benefits")).toBe(false);
  });

  it("layers supporter and patron benefits", () => {
    expect(tierAllowsEntitlement("supporter", "supporter_benefits")).toBe(true);
    expect(tierAllowsEntitlement("supporter", "patron_benefits")).toBe(false);
    expect(tierAllowsEntitlement("patron", "supporter_benefits")).toBe(true);
    expect(tierAllowsEntitlement("patron", "patron_benefits")).toBe(true);
  });

  it("honors explicit overrides and expiry", () => {
    const now = new Date("2026-11-23T00:00:00Z");
    expect(
      memberHasEntitlement({
        tierKey: "free",
        entitlement: "workshops",
        overrides: [{ entitlementKey: "workshops", enabled: true }],
        now,
      }),
    ).toBe(true);
    expect(
      memberHasEntitlement({
        tierKey: "standard",
        entitlement: "workshops",
        overrides: [{ entitlementKey: "workshops", enabled: false }],
        now,
      }),
    ).toBe(false);
    expect(
      memberHasEntitlement({
        tierKey: "free",
        entitlement: "workshops",
        overrides: [
          {
            entitlementKey: "workshops",
            enabled: true,
            expiresAt: new Date("2026-11-22T00:00:00Z"),
          },
        ],
        now,
      }),
    ).toBe(false);
  });

  it("fails closed without a tier", () => {
    expect(tierAllowsEntitlement(null, "announcements")).toBe(false);
    expect(
      memberHasEntitlement({ tierKey: null, entitlement: "public_events" }),
    ).toBe(false);
  });
});
