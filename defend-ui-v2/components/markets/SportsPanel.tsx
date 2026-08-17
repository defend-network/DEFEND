"use client";

import { useEffect, useState } from "react";
import {
  MarketsApiError,
  fetchCatalog,
  fetchList,
} from "@/lib/marketsApi";

type CatalogItem = Record<string, unknown>;

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

export function SportsPanel() {
  const [venues, setVenues] = useState<LoadState<CatalogItem[]>>({ kind: "loading" });
  const [instruments, setInstruments] = useState<LoadState<CatalogItem[]>>({ kind: "loading" });
  const [decisions, setDecisions] = useState<LoadState<CatalogItem[]>>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    const load = (promise: Promise<unknown>, apply: (value: unknown) => void) =>
      promise.then((value) => {
        if (!cancelled) apply(value);
      }).catch((error: unknown) => {
        if (!cancelled) {
          apply({
            kind: "unavailable",
            reason: error instanceof MarketsApiError ? `error ${error.status}` : "unreachable",
          });
        }
      });
    load(fetchCatalog("venues"), (value) =>
      setVenues({ kind: "ready", data: (value as { venues: CatalogItem[] }).venues })
    );
    load(fetchCatalog("instruments?desk=sports"), (value) =>
      setInstruments({ kind: "ready", data: (value as { instruments: CatalogItem[] }).instruments })
    );
    load(fetchList("/v1/decisions"), (value) =>
      setDecisions({ kind: "ready", data: (value as { decisions: CatalogItem[] }).decisions })
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = (state: LoadState<CatalogItem[]>) => {
    if (state.kind === "loading") return <p className="markets-note">Loading...</p>;
    if (state.kind === "unavailable")
      return <p className="markets-note">Unavailable: {state.reason}.</p>;
    if (state.data.length === 0)
      return <p className="markets-note">No live data yet.</p>;
    return (
      <ul className="markets-list">
        {state.data.map((item, index) => (
          <li key={String(item.instrument_key ?? item.venue_key ?? item.decision_id ?? index)}>
            <span className="markets-key">
              {String(item.instrument_key ?? item.venue_key ?? item.decision_id ?? "item")}
            </span>
          </li>
        ))}
      </ul>
    );
  };

  return (
    <section className="markets-panel">
      <h2>Sports</h2>
      <p className="markets-note">
        Real data read from the DEFEND Sports database through the Markets adapter. Nothing is fabricated.
      </p>
      <h3>Venues</h3>
      {rows(venues)}
      <h3>Instruments</h3>
      {rows(instruments)}
      <h3>Decisions</h3>
      {rows(decisions)}
    </section>
  );
}