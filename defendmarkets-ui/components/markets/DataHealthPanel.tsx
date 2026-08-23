"use client";

import { useEffect, useState } from "react";
import {
  DataHealthResponse,
  MarketsApiError,
  ProviderFeedResponse,
  fetchDataHealth,
  fetchProviders,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

function statusClass(status?: string): string {
  if (status === "HEALTHY") return "markets-on";
  if (status === "DEGRADED") return "markets-chip-stale";
  if (status === "UNCONFIGURED") return "markets-chip-unavailable";
  return "markets-off";
}

export function DataHealthPanel() {
  const [state, setState] = useState<LoadState<DataHealthResponse>>({ kind: "loading" });
  const [feeds, setFeeds] = useState<LoadState<ProviderFeedResponse>>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchDataHealth()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            kind: "unavailable",
            reason: error instanceof MarketsApiError ? `error ${error.status}` : "unreachable",
          });
        }
      });
    fetchProviders()
      .then((data) => {
        if (!cancelled) setFeeds({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setFeeds({
            kind: "unavailable",
            reason: error instanceof MarketsApiError ? `error ${error.status}` : "unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <p className="markets-note">Loading live data health...</p>;
  }
  if (state.kind === "unavailable") {
    return (
      <section className="markets-panel">
        <h2>Data Health</h2>
        <p className="markets-note">Unavailable: {state.reason}.</p>
      </section>
    );
  }

  const { quality_observations, sports_provider_health } = state.data;
  const providers = feeds.kind === "ready" ? feeds.data.providers : [];
  return (
    <section className="markets-panel">
      <h2>Data Health</h2>
      <h3>Live provider feeds</h3>
      {providers.length === 0 ? (
        <p className="markets-note">No feed probes recorded yet.</p>
      ) : (
        <ul className="markets-list">
          {providers.map((provider) => (
            <li key={provider.provider_id}>
              <span className="markets-key">{provider.provider_id}</span>{" "}
              <span className={statusClass(provider.status)}>{provider.status}</span>
              {typeof provider.records_ingested === "number" ? (
                <span className="markets-dim"> — {provider.records_ingested} records</span>
              ) : null}
              {provider.last_error ? (
                <span className="markets-dim"> ({provider.last_error})</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <h3>Sports provider health</h3>
      {sports_provider_health.length === 0 ? (
        <p className="markets-note">No provider health observations available.</p>
      ) : (
        <ul className="markets-list">
          {sports_provider_health.map((source) => (
            <li key={source.source_key}>
              <span className="markets-key">{source.source_key}</span>{" "}
              <span className={statusClass(source.status)}>{source.status}</span>
            </li>
          ))}
        </ul>
      )}
      <h3>Quality observations</h3>
      {quality_observations.length === 0 ? (
        <p className="markets-note">No quality observations recorded yet.</p>
      ) : (
        <ul className="markets-list">
          {quality_observations.map((observation) => (
            <li key={String(observation.quality_id ?? observation.instrument_key)}>
              <span className="markets-key">{String(observation.instrument_key)}</span>{" "}
              score {String(observation.score ?? "unknown")} —{" "}
              {String(observation.availability ?? "UNKNOWN")}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}