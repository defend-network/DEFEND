import { describe, expect, it } from "vitest";

import { isMfaSessionVerified } from "./mfa";

describe("session-level MFA verification", () => {
  const enabledAt = new Date("2026-11-23T12:00:00Z");

  it("fails closed when MFA is not enabled", () => {
    expect(
      isMfaSessionVerified({
        twoFactorEnabled: false,
        twoFactorEnabledAt: enabledAt,
        sessionCreatedAt: new Date("2026-11-23T12:05:00Z"),
      }),
    ).toBe(false);
  });

  it("fails closed when the enable timestamp is missing", () => {
    expect(
      isMfaSessionVerified({
        twoFactorEnabled: true,
        twoFactorEnabledAt: null,
        sessionCreatedAt: new Date("2026-11-23T12:05:00Z"),
      }),
    ).toBe(false);
  });

  it("rejects sessions created before MFA was enabled", () => {
    expect(
      isMfaSessionVerified({
        twoFactorEnabled: true,
        twoFactorEnabledAt: enabledAt,
        sessionCreatedAt: new Date("2026-11-23T11:55:00Z"),
      }),
    ).toBe(false);
  });

  it("accepts sessions created after MFA was enabled", () => {
    expect(
      isMfaSessionVerified({
        twoFactorEnabled: true,
        twoFactorEnabledAt: enabledAt,
        sessionCreatedAt: new Date("2026-11-23T12:05:00Z"),
      }),
    ).toBe(true);
  });

  it("accepts a session created at the enable timestamp", () => {
    expect(
      isMfaSessionVerified({
        twoFactorEnabled: true,
        twoFactorEnabledAt: enabledAt,
        sessionCreatedAt: new Date(enabledAt),
      }),
    ).toBe(true);
  });
});
