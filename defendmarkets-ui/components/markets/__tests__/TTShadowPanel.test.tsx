import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { TTShadowPanel } from "@/components/markets/TTShadowPanel";

const OVERVIEW_PAYLOAD = {
  as_of: "2026-08-20T12:00:00+00:00",
  collector: {
    events_discovered: 2,
    events_matched: 1,
    events_ambiguous: 0,
    events_unmatched: 1,
    prematch_observations: 4,
    postcommence_rejected: 1,
    bookmakers: ["1xbet", "bet365"],
    stale_events: 0,
  },
  m5: { available: 1, insufficient_history: 0 },
  evaluation: {
    n: 1,
    thresholds: { "30": null, "100": null, "250": null, "500": null, "1000": null },
    market_edge_status: "INSUFFICIENT_SAMPLE",
    pooled: { n: 1, m5_brier: 0.25 },
    per_class: {},
  },
};

const EVENTS_PAYLOAD = {
  as_of: "2026-08-20T12:00:00+00:00",
  events: [
    {
      forward_event_id: 1,
      player_a: "Sobisek Martin",
      player_b: "Chlebecek Marek",
      competition: "Czech Liga Pro",
      scheduled_commence: "2026-08-20T22:00:00+00:00",
      status: "PREMATCH",
      observation_count: 4,
      m5_p_a: 0.56,
      m5_availability: "AVAILABLE",
      model_market_disagreement: 0.0215,
    },
  ],
};

function stubFetch(payloads: Record<string, object>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      for (const [suffix, payload] of Object.entries(payloads)) {
        if (url.includes(suffix)) {
          return Promise.resolve(
            new Response(JSON.stringify(payload), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            })
          );
        }
      }
      return Promise.reject(new TypeError(`no stub for ${url}`));
    })
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TTShadowPanel", () => {
  beforeEach(() => {
    stubFetch({
      "/shadow/overview": OVERVIEW_PAYLOAD,
      "/shadow/events": EVENTS_PAYLOAD,
    });
  });

  it("renders collector counts and bookmakers", async () => {
    render(<TTShadowPanel />);
    expect(await screen.findByText(/Forward events/)).toBeDefined();
    expect(screen.getByText("1xbet, bet365")).toBeDefined();
  });

  it("renders M5 availability and edge status gate", async () => {
    render(<TTShadowPanel />);
    expect(await screen.findByText(/M5 live inference/)).toBeDefined();
    expect(screen.getByText(/INSUFFICIENT_SAMPLE/)).toBeDefined();
    expect(screen.getByText(/no wagers are placed/)).toBeDefined();
  });

  it("renders the event row with status and disagreement", async () => {
    render(<TTShadowPanel />);
    expect(await screen.findByText(/Sobisek Martin/)).toBeDefined();
    expect(screen.getByText("PREMATCH")).toBeDefined();
    expect(screen.getByText("0.0215")).toBeDefined();
  });

  it("shows an explicit unavailable state when the API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("network down"))));
    render(<TTShadowPanel />);
    expect(await screen.findByText(/TT SHADOW/)).toBeDefined();
    expect(screen.getByText(/Unavailable: markets API unreachable/)).toBeDefined();
  });
});