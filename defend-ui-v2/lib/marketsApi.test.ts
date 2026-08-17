import { describe, expect, it, vi, afterEach } from "vitest";
import {
  MarketsApiError,
  MARKETS_API_BASE,
  fetchOverview,
  evaluateSports,
  fetchTableTennisBoard,
  fetchPerformance,
  fetchDecisions,
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

  it("fetchTableTennisBoard reads the live board endpoint", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ events: [], provider_health: [], now: "t" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchTableTennisBoard();
    expect(result.events).toEqual([]);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(`${MARKETS_API_BASE}/v1/sports/table-tennis`);
  });

  it("fetchPerformance reads the performance endpoint", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            sample_size: { decisions: 0, opportunities: 0, no_actions: 0, settled: 0 },
            roi: { available: false },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchPerformance();
    expect(result.sample_size.decisions).toBe(0);
    expect(result.roi.available).toBe(false);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(`${MARKETS_API_BASE}/v1/performance`);
  });

  it("fetchDecisions passes the limit through", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ decisions: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchDecisions(25);
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe(`${MARKETS_API_BASE}/v1/decisions?limit=25`);
  });
});