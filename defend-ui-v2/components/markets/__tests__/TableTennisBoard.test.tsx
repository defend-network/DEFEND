import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TableTennisBoard } from "@/components/markets/TableTennisBoard";

const BOARD_PAYLOAD = {
  events: [
    {
      event_key: "tt-live-001",
      display_name: "Player A vs Player B",
      scheduled_at: null,
      league_key: "tt_wtt",
      market_key: "match_winner",
      live: {
        state: { status: "live", sets: [1, 0], points: [9, 7], server: "home" },
        observed_at: "2026-08-15T11:55:00+00:00",
      },
      legs: [
        {
          selection_key: "player_a",
          display_name: "Player A",
          decimal_odds: "1.85",
          implied_probability: "0.5405",
          source_key: "book-a",
          observed_at: "2026-08-15T11:50:00+00:00",
        },
        {
          selection_key: "player_b",
          display_name: "Player B",
          decimal_odds: "2.35",
          implied_probability: "0.4255",
          source_key: "book-b",
          observed_at: "2026-08-15T11:50:00+00:00",
        },
      ],
      gross_edge: "0.034",
      costs: { components: { total: null }, total: null },
      net_edge: null,
      confidence: "0.9",
      model_probability: null,
      model_probability_available: false,
      data_quality: "0.9",
      freshness: { ok: true, status: "HEALTHY", age_seconds: 300 },
      strategy: {
        key: "tt_two_way_arb",
        version: 1,
        lifecycle: "EXPERIMENTAL",
        eligible: true,
        reasons: ["two_way_arb"],
      },
      decision: {
        decision_id: "abc",
        decision_type: "OPPORTUNITY",
        reason_codes: [],
        estimated_edge: "0.03",
        created_at: "2026-08-15T11:55:00+00:00",
      },
    },
    {
      event_key: "tt-live-002",
      display_name: "Player C vs Player D",
      scheduled_at: null,
      league_key: "tt_wtt",
      market_key: "match_winner",
      live: null,
      legs: [],
      gross_edge: null,
      costs: { components: { total: null }, total: null },
      net_edge: null,
      confidence: null,
      model_probability: null,
      model_probability_available: false,
      data_quality: "0",
      freshness: { ok: false, status: "UNAVAILABLE", age_seconds: null },
      strategy: {
        key: "tt_two_way_arb",
        version: 1,
        lifecycle: "EXPERIMENTAL",
        eligible: false,
        reasons: ["requires_exactly_two_selections"],
      },
      decision: {
        decision_id: "def",
        decision_type: "NO_ACTION",
        reason_codes: ["no_eligible_data"],
        created_at: "2026-08-15T11:55:00+00:00",
      },
    },
  ],
  provider_health: [
    { source_key: "book-a", status: "HEALTHY" },
    { source_key: "book-b", status: "HEALTHY" },
  ],
  strategy_key: "tt_two_way_arb",
  market_key: "match_winner",
  now: "2026-08-15T12:00:00+00:00",
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(BOARD_PAYLOAD), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    )
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TableTennisBoard", () => {
  it("renders match identity, live state and real odds", async () => {
    render(<TableTennisBoard />);
    expect(await screen.findByText("Player A vs Player B")).toBeDefined();
    expect(screen.getByText(/Sets 1-0 · Pts 9-7 · Server home/)).toBeDefined();
    expect(screen.getByText(/player_a 1.85 · player_b 2.35/)).toBeDefined();
  });

  it("shows gross edge and explicit unaccounted costs instead of invented values", async () => {
    render(<TableTennisBoard />);
    await screen.findByText("Player A vs Player B");
    expect(screen.getByText(/3\.400%/)).toBeDefined();
    expect(screen.getAllByText(/unaccounted/).length).toBeGreaterThan(0);
  });

  it("labels model probability as not wired rather than fabricating it", async () => {
    render(<TableTennisBoard />);
    await screen.findByText("Player A vs Player B");
    expect(screen.getAllByText(/not wired/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/model probability \d/)).toBeNull();
  });

  it("renders OPPORTUNITY and NO_ACTION decision badges", async () => {
    render(<TableTennisBoard />);
    await screen.findByText("Player A vs Player B");
    expect(screen.getByText(/OPPORTUNITY/)).toBeDefined();
    expect(screen.getByText(/NO_ACTION/)).toBeDefined();
  });

  it("marks matches without live state explicitly", async () => {
    render(<TableTennisBoard />);
    await screen.findByText("Player A vs Player B");
    expect(screen.getAllByText(/live score not wired/).length).toBe(1);
  });

  it("shows an explicit unavailable state when the API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("network down")))
    );
    render(<TableTennisBoard />);
    expect(
      await screen.findByText(/Board unavailable: markets API unreachable/)
    ).toBeDefined();
  });
});