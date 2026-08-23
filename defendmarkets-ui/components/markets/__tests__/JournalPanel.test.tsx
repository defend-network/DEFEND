import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { JournalPanel } from "@/components/markets/JournalPanel";

const PERFORMANCE_PAYLOAD = {
  sample_size: { decisions: 4, opportunities: 1, no_actions: 3, settled: 2 },
  no_action_pct: 0.75,
  net_pnl: 4.5,
  win_rate: 0.5,
  roi: { value: null, available: false, reason: "no stake basis is recorded" },
  clv: { value: 0.03, available: true, reason: null },
  calibration: {
    available: true,
    buckets: { "0.85-1.00": 2 },
    reason: null,
  },
  max_drawdown: {
    value: 8.0,
    available: true,
    reason: null,
  },
  as_of: "2026-08-15T12:00:00+00:00",
};

const DECISIONS_PAYLOAD = {
  decisions: [
    {
      decision_id: "d-1",
      strategy_key: "tt_two_way_arb",
      policy_key: "markets_core",
      decision_type: "NO_ACTION",
      reason_codes: ["costs_unaccounted"],
      thesis: "no venue cost model yet",
      estimated_edge: null,
      cost_estimate: null,
      created_at: "2026-08-15T11:00:00+00:00",
      instrument_key: "sports:tt-live-001:match_winner",
    },
    {
      decision_id: "d-2",
      strategy_key: "tt_two_way_arb",
      policy_key: "markets_core",
      decision_type: "OPPORTUNITY",
      reason_codes: [],
      thesis: "real observed odds",
      estimated_edge: "0.03",
      cost_estimate: "0.001",
      created_at: "2026-08-15T11:30:00+00:00",
      instrument_key: "sports:tt-live-002:match_winner",
    },
  ],
};

beforeEach(() => {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("/v1/performance")) {
      return Promise.resolve(
        new Response(JSON.stringify(PERFORMANCE_PAYLOAD), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    }
    if (url.includes("/v1/decisions")) {
      return Promise.resolve(
        new Response(JSON.stringify(DECISIONS_PAYLOAD), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    }
    return Promise.reject(new TypeError(`unexpected url ${url}`));
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("JournalPanel", () => {
  it("renders performance panels from real aggregates", async () => {
    render(<JournalPanel />);
    expect(await screen.findByText("Net ROI")).toBeDefined();
    expect(screen.getByText(/75\.0%/)).toBeDefined();
    expect(screen.getByText(/\$4\.50/)).toBeDefined();
    expect(screen.getByText(/50\.0%/)).toBeDefined();
  });

  it("shows not wired for metrics without a real basis", async () => {
    render(<JournalPanel />);
    await screen.findByText("Net ROI");
    expect(screen.getByText(/no stake basis is recorded/)).toBeDefined();
  });

  it("renders the journaled decisions with identity and reason codes", async () => {
    render(<JournalPanel />);
    expect(await screen.findByText(/tt-live-001 · match_winner/)).toBeDefined();
    expect(screen.getByText(/costs_unaccounted/)).toBeDefined();
    expect(screen.getByText(/tt-live-002 · match_winner/)).toBeDefined();
  });

  it("handles an unreachable API honestly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("network down")))
    );
    render(<JournalPanel />);
    expect(
      await screen.findByText(/Performance unavailable: unreachable/)
    ).toBeDefined();
  });
});