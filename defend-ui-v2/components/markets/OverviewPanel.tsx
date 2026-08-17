"use client";

import { useEffect, useState } from "react";
import {
  MarketsApiError,
  OverviewResponse,
  fetchOverview,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

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
      <section className="markets-panel">
        <h2>Overview</h2>
        <p className="markets-note">Unavailable: {state.reason}. Data shown only when the API answers.</p>
      </section>
    );
  }

  const { counts, venues, provider_health, desks, pit_availability } = state.data;
  return (
    <section className="markets-panel">
      <h2>Overview</h2>
      <dl className="markets-grid">
        <div>
          <dt>Venues</dt>
          <dd>{venues}</dd>
        </div>
        <div>
          <dt>Instruments</dt>
          <dd>{counts.market_instruments ?? 0}</dd>
        </div>
        <div>
          <dt>Opportunities</dt>
          <dd>{counts.market_opportunities ?? 0}</dd>
        </div>
        <div>
          <dt>Decisions</dt>
          <dd>{counts.market_decisions ?? 0}</dd>
        </div>
        <div>
          <dt>Strategies</dt>
          <dd>{counts.market_strategies ?? 0}</dd>
        </div>
        <div>
          <dt>Risk policies</dt>
          <dd>{counts.market_risk_policies ?? 0}</dd>
        </div>
      </dl>

      <h3>Desks</h3>
      <ul className="markets-list">
        {Object.entries(desks).map(([desk, state]) => (
          <li key={desk}>
            <span className="markets-key">{desk}</span>{" "}
            <span className={state.available ? "markets-on" : "markets-off"}>
              {state.available ? state.status : "pending"}
            </span>
          </li>
        ))}
      </ul>

      <h3>Provider health</h3>
      {provider_health.sources.length === 0 ? (
        <p className="markets-note">No provider health observations available.</p>
      ) : (
        <ul className="markets-list">
          {provider_health.sources.map((source) => (
            <li key={source.source_key}>
              <span className="markets-key">{source.source_key}</span>{" "}
              <span className={source.status === "HEALTHY" ? "markets-on" : "markets-off"}>
                {source.status}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Point-in-time fields provided</h3>
      {pit_availability.length === 0 ? (
        <p className="markets-note">No sports data source configured.</p>
      ) : (
        <ul className="markets-list">
          {pit_availability.map((field) => (
            <li key={field}>{field}</li>
          ))}
        </ul>
      )}
    </section>
  );
}