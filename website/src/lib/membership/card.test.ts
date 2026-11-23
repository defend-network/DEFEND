import { beforeAll, describe, expect, it } from "vitest";

import { createCardToken, verifyCardToken } from "@/lib/membership/card";

beforeAll(() => {
  process.env.CARD_TOKEN_SECRET = "test-card-signing-secret-with-enough-entropy";
});

describe("membership card tokens", () => {
  it("creates a verifiable short-lived token without personal information", async () => {
    const { token } = await createCardToken({
      membershipId: "membership_1",
      userId: "user_1",
      ttlSeconds: 300,
    });
    expect(token).toMatch(/^v1\./);
    expect(token).not.toContain("user_1");
    expect(token).not.toContain("membership_1");
    const payload = await verifyCardToken(token);
    expect(payload?.membershipId).toBe("membership_1");
    expect(payload?.userId).toBe("user_1");
  });

  it("rejects tampered tokens", async () => {
    const { token } = await createCardToken({
      membershipId: "membership_1",
      userId: "user_1",
    });
    const parts = token.split(".");
    const signature = parts[2];
    const flipped = `${signature[0] === "A" ? "B" : "A"}${signature.slice(1)}`;
    const tampered = `${parts[0]}.${parts[1]}.${flipped}`;
    expect(await verifyCardToken(tampered)).toBeNull();
  });

  it("rejects expired tokens", async () => {
    const { token } = await createCardToken({
      membershipId: "membership_1",
      userId: "user_1",
      ttlSeconds: -1,
    });
    expect(await verifyCardToken(token)).toBeNull();
  });
});
