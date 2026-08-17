import { describe, expect, it, vi, afterEach } from "vitest";
import {
  MarketsApiError,
  MARKETS_API_BASE,
  fetchOverview,
  evaluateSports,
} from "@/lib/marketsApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("marketsApi", () => {
  it("uses the configured API base without trailing slash", () => {
    expect(MARKETS_API_BASE.endsWith("/")).toBe(false);
  });

  it("reports unreachable API as a typed error", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("network down"))));
    await expect(fetchOverview()).rejects.toBeInstanceOf(MarketsApiError);
    await expect(fetchOverview()).rejects.toMatchObject({ status: 0 });
  });

  it("reports non-2xx responses as typed errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("{}", { status: 503 })))
    );
    await expect(fetchOverview()).rejects.toMatchObject({ status: 503 });
  });

  it("evaluateSports posts the sports payload", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            decision_type: "NO_ACTION",
            reason_codes: ["costs_unaccounted"],
            policy_version: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await evaluateSports("tt-live-001", "match_winner");
    expect(result.decision_type).toBe("NO_ACTION");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${MARKETS_API_BASE}/v1/evaluate/sports`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toMatchObject({
      event_key: "tt-live-001",
      market_key: "match_winner",
      strategy_key: "tt_two_way_arb",
      policy_key: "markets_core",
    });
  });
});