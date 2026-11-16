import { describe, expect, it } from "vitest";

import {
  createUnsubscribeToken,
  newsletterUnsubscribeUrl,
  verifyUnsubscribeToken,
} from "./tokens";

describe("newsletter unsubscribe tokens", () => {
  it("round-trips a subscriber id", async () => {
    const token = await createUnsubscribeToken("news_123");
    await expect(verifyUnsubscribeToken(token)).resolves.toEqual({
      valid: true,
      subscriberId: "news_123",
    });
  });

  it("rejects a modified token", async () => {
    const token = await createUnsubscribeToken("news_123");
    await expect(verifyUnsubscribeToken(`${token}x`)).resolves.toEqual({
      valid: false,
    });
  });

  it("rejects malformed tokens", async () => {
    await expect(verifyUnsubscribeToken("not-a-token")).resolves.toEqual({
      valid: false,
    });
  });

  it("builds an absolute unsubscribe URL", async () => {
    const url = await newsletterUnsubscribeUrl("news_123");
    expect(url).toMatch(/\/newsletter\/unsubscribe\?token=v1\./);
  });
});
