import { describe, expect, it } from "vitest";

import { redactAuditMetadata } from "@/lib/audit/audit";

describe("audit metadata redaction", () => {
  it("redacts sensitive keys at any depth", () => {
    const result = redactAuditMetadata({
      action: "member.update",
      email: "person@example.com",
      password: "secret",
      nested: { token: "abc", note: "private", safe: 7 },
      items: [{ phone: "555-0100", label: "home" }],
    }) as Record<string, unknown>;

    expect(result.action).toBe("member.update");
    expect(result.email).toBe("[redacted]");
    expect(result.password).toBe("[redacted]");
    const nested = result.nested as Record<string, unknown>;
    expect(nested.token).toBe("[redacted]");
    expect(nested.note).toBe("[redacted]");
    expect(nested.safe).toBe(7);
    const items = result.items as Array<Record<string, unknown>>;
    expect(items[0].phone).toBe("[redacted]");
    expect(items[0].label).toBe("home");
  });

  it("bounds long strings and arrays", () => {
    const result = redactAuditMetadata({
      long: "x".repeat(700),
      list: Array.from({ length: 60 }, (_, index) => index),
    }) as Record<string, unknown>;
    expect((result.long as string).length).toBeLessThanOrEqual(501);
    expect((result.list as unknown[]).length).toBe(25);
  });
});
