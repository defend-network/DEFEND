import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getSetupDiagnostics,
  getSetupSummary,
  removeSetupSecret,
  saveSetupSecret,
  testAllSetupProviders,
} from "@/lib/setupApi";

function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

function okJson(payload: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("setup API client", () => {
  it("sends the bearer token and include credentials on every call", async () => {
    stubFetch(() => okJson({ rows: [] }));
    await getSetupDiagnostics("token-1");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/admin/setup/diagnostics");
    expect(init).toMatchObject({
      credentials: "include",
      headers: { Authorization: "Bearer token-1" },
    });
  });

  it("passes through a server-provided detail message", async () => {
    stubFetch(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: "rotation required" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(getSetupSummary("token-1")).rejects.toThrow(
      "rotation required",
    );
  });

  it("never leaks a non-JSON upstream error body", async () => {
    const sentinel = "private-html-5xx-detail";
    stubFetch(() =>
      Promise.resolve(
        new Response(`<!DOCTYPE html><p>${sentinel}</p>`, { status: 502 }),
      ),
    );
    const request = getSetupSummary("token-1");
    await expect(request).rejects.toThrow("Request failed (502)");
    await expect(request).rejects.not.toThrow(sentinel);
  });

  it("maps network failures to an actionable message", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(testAllSetupProviders("token-1")).rejects.toThrow(
      "Failed to fetch — API unreachable. Is the API server running locally?",
    );
  });

  it("maps aborted requests to a timeout message", async () => {
    stubFetch(() =>
      Promise.reject(new DOMException("The operation was aborted.", "AbortError")),
    );
    await expect(saveSetupSecret("token-1", "fred", "FRED_API_KEY", "k")).rejects.toThrow(
      "Setup request timed out.",
    );
  });

  it("sends secret values only in the request body, never in the URL", async () => {
    stubFetch(() => okJson({ ok: true }));
    await saveSetupSecret("token-1", "fred", "FRED_API_KEY", "super-secret-v9");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).not.toContain("super-secret-v9");
    expect(JSON.parse(String(init?.body))).toEqual({
      secret_name: "FRED_API_KEY",
      value: "super-secret-v9",
    });
    await removeSetupSecret("token-1", "fred", "FRED_API_KEY");
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(
      "/api/admin/setup/providers/fred/secret?secret_name=FRED_API_KEY",
    );
  });
});
