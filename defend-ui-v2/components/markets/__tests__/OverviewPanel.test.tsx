import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { OverviewPanel } from "@/components/markets/OverviewPanel";

const OVERVIEW_PAYLOAD = {
  application_id: "markets",
  counts: {
    market_instruments: 3,
    market_events: 1,
    market_strategies: 2,
    market_risk_policies: 1,
    market_opportunities: 1,
    market_decisions: 2,
    market_outcomes: 0,
    market_data_quality: 0,
  },
  venues: 2,
  provider_health: {
    ok: true,
    sources: [
      { source_key: "book-a", status: "HEALTHY" },
      { source_key: "book-b", status: "HEALTHY" },
    ],
  },
  desks: {
    overview: { available: true, status: "ready" },
    opportunities: { available: true, status: "ready" },
    sports: { available: true, status: "ready" },
    equities: { available: false, status: "pending" },
    macro: { available: false, status: "pending" },
    crypto: { available: false, status: "pending" },
    events: { available: false, status: "pending" },
    strategies: { available: true, status: "ready" },
    backtests: { available: false, status: "pending" },
    journal: { available: true, status: "ready" },
    data_health: { available: true, status: "ready" },
  },
  pit_availability: ["observed_at", "received_at", "scheduled_at", "raw_ref"],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(OVERVIEW_PAYLOAD), {
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

describe("OverviewPanel", () => {
  it("renders live totals from the real overview endpoint", async () => {
    render(<OverviewPanel />);
    expect(await screen.findByText("DEFENDmarkets")).toBeDefined();
    expect(screen.getByText("2/2 providers healthy")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
  });

  it("separates desks and marks pending desks as not wired", async () => {
    render(<OverviewPanel />);
    await screen.findByText("DEFENDmarkets");
    expect(screen.getByText("Arbitrage")).toBeDefined();
    expect(screen.getByText("Table Tennis")).toBeDefined();
    expect(screen.getByText("Prediction Markets")).toBeDefined();
    expect(screen.getByText("Macro / Events")).toBeDefined();
    expect(screen.getByText("Crypto")).toBeDefined();
    expect(screen.getByText("Journal / Performance")).toBeDefined();
    expect(screen.getAllByText("not wired").length).toBeGreaterThan(0);
  });

  it("links desks to their sections", async () => {
    render(<OverviewPanel />);
    await screen.findByText("DEFENDmarkets");
    expect(screen.getByRole("link", { name: /Table Tennis/ })).toHaveAttribute(
      "href",
      "/markets/sports"
    );
    expect(screen.getByRole("link", { name: /Journal \/ Performance/ })).toHaveAttribute(
      "href",
      "/markets/journal"
    );
  });

  it("shows an explicit unavailable state when the API is offline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("network down")))
    );
    render(<OverviewPanel />);
    expect(await screen.findByText(/API unavailable/)).toBeDefined();
  });
});