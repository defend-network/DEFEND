import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TTDataStatusPanel } from "@/components/markets/TTDataStatusPanel";

const READY_PAYLOAD = {
  as_of: "2026-08-17T12:00:00+00:00",
  key: { configured: true, source: "environment", entry_point: "Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY" },
  results_feed: {
    provider_id: "the_odds_api_tt",
    configured: true,
    status: "HEALTHY",
    last_attempt_at: "2026-08-17T11:00:00+00:00",
    last_success_at: "2026-08-17T11:00:00+00:00",
    last_error: null,
    records_ingested: 12,
  },
  odds_feed: {
    provider_id: "the_odds_api",
    configured: true,
    status: "HEALTHY",
    last_success_at: "2026-08-17T11:00:00+00:00",
    live_events: 3,
  },
  model_history: {
    completed_matches: 24,
    players_with_history: 8,
    min_games_per_player: 5,
    players_over_threshold: 6,
    ready: true,
    top_players: [
      { participant_key: "tabletennis:alice", games: 9 },
      { participant_key: "tabletennis:bob", games: 7 },
    ],
  },
  note: "free tier: 500 credits/month",
};

const COLD_PAYLOAD = {
  as_of: "2026-08-17T12:00:00+00:00",
  key: { configured: false, source: null, entry_point: "Setup & Integrations -> The Odds API -> THE_ODDS_API_KEY" },
  results_feed: {
    provider_id: "the_odds_api_tt",
    configured: false,
    status: "UNCONFIGURED",
    last_attempt_at: null,
    last_success_at: null,
    last_error: null,
    records_ingested: null,
  },
  odds_feed: {
    provider_id: "the_odds_api",
    configured: false,
    status: "NOT_POLLED",
    last_success_at: null,
    live_events: 0,
  },
  model_history: {
    completed_matches: 0,
    players_with_history: 0,
    min_games_per_player: 5,
    players_over_threshold: 0,
    ready: false,
    top_players: [],
  },
  note: "free tier: 500 credits/month",
};

function stubFetch(payload: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    )
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TTDataStatusPanel", () => {
  beforeEach(() => {
    stubFetch(READY_PAYLOAD);
  });

  it("renders both feeds as configured when the key is present", async () => {
    render(<TTDataStatusPanel />);
    expect(await screen.findByText(/Odds feed \(the_odds_api\)/)).toBeDefined();
    expect(screen.getByText(/Results feed \(the_odds_api_tt\)/)).toBeDefined();
    expect(screen.getAllByText(/HEALTHY/).length).toBeGreaterThanOrEqual(2);
  });

  it("shows completed match count and players with history", async () => {
    render(<TTDataStatusPanel />);
    await screen.findByText(/Completed TT matches/);
    expect(screen.getByText("24")).toBeDefined();
    expect(screen.getByText("8")).toBeDefined();
  });

  it("reports READY once two players pass the game threshold", async () => {
    render(<TTDataStatusPanel />);
    expect(await screen.findByText(/READY/)).toBeDefined();
    expect(screen.getByText(/tabletennis:alice \(9\)/)).toBeDefined();
  });

  it("shows the entry point when the key is missing", async () => {
    stubFetch(COLD_PAYLOAD);
    render(<TTDataStatusPanel />);
    expect(await screen.findByText(/Setup & Integrations → The Odds API/)).toBeDefined();
    expect(screen.getAllByText(/UNCONFIGURED/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/insufficient · 0\/5-game threshold/)).toBeDefined();
  });

  it("shows an explicit unavailable state when the API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("network down"))));
    render(<TTDataStatusPanel />);
    expect(await screen.findByText(/TT DATA/)).toBeDefined();
    expect(screen.getByText(/Unavailable: markets API unreachable/)).toBeDefined();
  });
});
