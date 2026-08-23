import { describe, it, expect } from "vitest";
import { resolveInternalApiOrigin } from "@/lib/proxyOrigin.mjs";

describe("resolveInternalApiOrigin", () => {
  it("defaults to loopback with the product API port", () => {
    expect(resolveInternalApiOrigin({})).toBe("http://127.0.0.1:8500");
  });

  it("uses a configured loopback origin", () => {
    expect(
      resolveInternalApiOrigin({ MARKETS_INTERNAL_API_ORIGIN: "http://localhost:8500" }),
    ).toBe("http://localhost:8500");
  });

  it("allows ::1 loopback", () => {
    expect(
      resolveInternalApiOrigin({ MARKETS_INTERNAL_API_ORIGIN: "http://[::1]:8500" }),
    ).toBe("http://[::1]:8500");
  });

  it("rejects an external host (no SSRF)", () => {
    expect(() =>
      resolveInternalApiOrigin({ MARKETS_INTERNAL_API_ORIGIN: "https://evil.example.com" }),
    ).toThrow(/loopback/);
  });

  it("rejects a non-http scheme", () => {
    expect(() =>
      resolveInternalApiOrigin({ MARKETS_INTERNAL_API_ORIGIN: "https://127.0.0.1:8500" }),
    ).toThrow(/http/);
  });

  it("rejects a caller/browser-selected upstream", () => {
    expect(() =>
      resolveInternalApiOrigin({ MARKETS_INTERNAL_API_ORIGIN: "http://192.168.1.5:8500" }),
    ).toThrow(/loopback/);
  });
});
