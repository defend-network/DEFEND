import { describe, expect, it } from "vitest";

import { isSessionMfaVerified } from "./mfa";

describe("session-level MFA verification", () => {
  it("fails closed when the session has no MFA marker", () => {
    expect(isSessionMfaVerified(null)).toBe(false);
    expect(isSessionMfaVerified(undefined)).toBe(false);
  });

  it("accepts a session with a valid MFA verification timestamp", () => {
    expect(isSessionMfaVerified(new Date("2026-11-23T12:00:00Z"))).toBe(true);
  });

  it("rejects an invalid timestamp", () => {
    expect(isSessionMfaVerified(new Date("invalid"))).toBe(false);
  });
});
