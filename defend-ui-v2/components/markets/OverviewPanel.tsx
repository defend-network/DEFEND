"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  DeskState,
  MarketsApiError,
  OverviewResponse,
  fetchOverview,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

type DeskCard = {
  id: string;
  label: string;
  tagline: string;
  href: string;
};

const DESK_CARDS: DeskCard[] = [
  {
    id: "opportunities",
    label: "Arbitrage",
    tagline: "Ranked two-way arbitrage opportunities across venues.",
    href: "/markets/opportunities",
  },
  {
    id: "sports",
    label: "Table Tennis",
    tagline: "Live decision board — odds, edges, health, decisions.",
    href: "/markets/sports",
  },
  {
    id: "events",
    label: "Prediction Markets",
    tagline: "Event-contract markets. Desk is pending.",
    href: "/markets/events",
  },
  {
    id: "macro",
    label: "Macro / Events",
    tagline: "Macro series and event impacts. Desk is pending.",
    href: "/markets/macro",
  },
  {
    id: "crypto",
    label: "Crypto",
    tagline: "Spot and derivative instruments. Desk is pending.",
    href: "/markets/crypto",
  },
  {
    id: "journal",
    label: "Journal / Performance",
    tagline: "Append-only decision journal and honest performance panels.",
    href: "/markets/journal",
  },
];

const API_DESK_LABELS: Record<string, string> = {
  overview: "Overview",
  opportunities: "Arbitrage",
  sports: "Table Tennis",
  equities: "Equities",
  macro: "Macro",
  crypto: "Crypto",
  events: "Prediction Markets",
  strategies: "Strategies",
  backtests: "Backtests",
  journal: "Journal",
  data_health: "Data Health",
};

export function OverviewPanel() {
  const [state, setState] = useState<LoadState<OverviewResponse>>({
    kind: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    fetchOverview()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            kind: "unavailable",
            reason:
              error instanceof MarketsApiError
                ? `markets API error ${error.status}`
                : "markets API unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <p className="markets-note">Loading live state from DEFENDmarkets API...</p>;
  }
  if (state.kind === "unavailable") {
    return (
      <div className="dm-board">
        <section className="dm-panel">
          <span className="dm-eyebrow">DEFENDmarkets</span>
          <h2>API unavailable</h2>
          <p className="markets-note">
            {state.reason}. The dashboard only renders real state — nothing is fabricated
            while the markets API is offline.
          </p>
        </section>
      </div>
    );
  }

  const { counts, venues, provider_health, desks, pit_availability } = state.data;
  const healthySources = provider_health.sources.filter(
    (source) => source.status === "HEALTHY"
  ).length;
  const apiReady = healthySources === provider_health.sources.length && provider_health.sources.length > 0;

  return (
    <div className="dm-board">
      <section className="dm-hero">
        <div className="dm-hero-copy">
          <span className="dm-eyebrow">Cross-market research · ranking · decision engine</span>
          <h1>DEFENDmarkets</h1>
          <p>
            Live desks for arbitrage, sports, prediction markets, macro, crypto and the
            performance journal. Every number on this product is read from real database
            state; unavailable desks say so explicitly.
          </p>
        </div>
        <div className="dm-hero-meta">
          <span className={`dm-chip${apiReady ? " dm-chip-on" : " dm-chip-warn"}`}>
            API {apiReady ? "healthy" : "degraded"}
          </span>
          <span className="dm-chip dm-chip-muted">
            {healthySources}/{provider_health.sources.length || 0} providers healthy
          </span>
        </div>
      </section>

      <section className="dm-kpis" aria-label="Live totals">
        <div className="dm-kpi">
          <span className="dm-kpi-k">Venues</span>
          <span className="dm-kpi-v">{venues}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Instruments</span>
          <span className="dm-kpi-v">{counts.market_instruments ?? 0}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Opportunities</span>
          <span className="dm-kpi-v">{counts.market_opportunities ?? 0}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Decisions</span>
          <span className="dm-kpi-v">{counts.market_decisions ?? 0}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Strategies</span>
          <span className="dm-kpi-v">{counts.market_strategies ?? 0}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Risk policies</span>
          <span className="dm-kpi-v">{counts.market_risk_policies ?? 0}</span>
        </div>
      </section>

      <section className="dm-panel">
        <h2>Desks</h2>
        <div className="dm-desk-grid">
          {DESK_CARDS.map((card) => {
            const desk = desks[card.id];
            const available = desk?.available === true;
            return (
              <Link key={card.id} href={card.href} className="dm-desk">
                <div className="dm-desk-head">
                  <strong>{card.label}</strong>
                  <span
                    className={`dm-chip${available ? " dm-chip-on" : " dm-chip-off"}`}
                  >
                    {available ? "ready" : "not wired"}
                  </span>
                </div>
                <p>{card.tagline}</p>
                {!available && (
                  <small className="dm-desk-note">
                    No backend desk yet — this section stays explicit, never simulated.
                  </small>
                )}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="dm-panel">
        <h2>Provider health</h2>
        {provider_health.sources.length === 0 ? (
          <p className="markets-note">No provider health observations available.</p>
        ) : (
          <ul className="dm-health-list">
            {provider_health.sources.map((source) => (
              <li key={source.source_key}>
                <span className="dm-health-key">{source.source_key}</span>
                <span className={`dm-chip${source.status === "HEALTHY" ? " dm-chip-on" : " dm-chip-warn"}`}>
                  {source.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="dm-panel">
        <h2>Point-in-time fields</h2>
        {pit_availability.length === 0 ? (
          <p className="markets-note">No sports data source configured.</p>
        ) : (
          <div className="dm-pit">
            {pit_availability.map((field) => (
              <span key={field} className="dm-chip dm-chip-muted">
                {field}
              </span>
            ))}
          </div>
        )}
        {Object.entries(desks).length > 0 && (
          <p className="dm-desk-legend">
            Desk registry:{" "}
            {Object.entries(desks)
              .map(([id, desk]: [string, DeskState]) => `${API_DESK_LABELS[id] ?? id} ${desk.available ? "ready" : "pending"}`)
              .join(" · ")}
          </p>
        )}
      </section>
    </div>
  );
}