import { describe, expect, it } from "vitest";

import {
  generateInvitationToken,
  hashInvitationToken,
  invitationState,
  isAcceptablePassword,
  normalizeEmail,
} from "@/lib/auth/invitations";

describe("invitation security primitives", () => {
  it("generates high-entropy prefixed tokens", () => {
    const first = generateInvitationToken();
    const second = generateInvitationToken();
    expect(first.token).toMatch(/^inv_[A-Za-z0-9_-]{40,}$/);
    expect(first.token).not.toBe(second.token);
  });

  it("hashes tokens deterministically without exposing the raw token", async () => {
    const { token } = generateInvitationToken();
    const first = await hashInvitationToken(token);
    const second = await hashInvitationToken(token);
    expect(first).toBe(second);
    expect(first).toMatch(/^[a-f0-9]{64}$/);
    expect(first).not.toContain(token);
  });

  it("classifies invitation state in the correct order", () => {
    const now = new Date("2026-11-15T12:00:00Z");
    expect(
      invitationState(
        {
          expiresAt: new Date("2026-11-16T12:00:00Z"),
          consumedAt: null,
          revokedAt: null,
        },
        now,
      ),
    ).toBe("pending");
    expect(
      invitationState(
        {
          expiresAt: new Date("2026-11-14T12:00:00Z"),
          consumedAt: null,
          revokedAt: null,
        },
        now,
      ),
    ).toBe("expired");
    expect(
      invitationState(
        {
          expiresAt: new Date("2026-11-16T12:00:00Z"),
          consumedAt: new Date("2026-11-15T10:00:00Z"),
          revokedAt: null,
        },
        now,
      ),
    ).toBe("consumed");
    expect(
      invitationState(
        {
          expiresAt: new Date("2026-11-16T12:00:00Z"),
          consumedAt: null,
          revokedAt: new Date("2026-11-15T10:00:00Z"),
        },
        now,
      ),
    ).toBe("revoked");
  });

  it("enforces acceptable password length", () => {
    expect(isAcceptablePassword("short")).toBe(false);
    expect(isAcceptablePassword("a".repeat(11))).toBe(false);
    expect(isAcceptablePassword("a".repeat(12))).toBe(true);
    expect(isAcceptablePassword("a".repeat(512))).toBe(true);
    expect(isAcceptablePassword("a".repeat(513))).toBe(false);
  });

  it("normalizes email for canonical lookups", () => {
    expect(normalizeEmail("  Person@Example.COM ")).toBe("person@example.com");
  });
});
