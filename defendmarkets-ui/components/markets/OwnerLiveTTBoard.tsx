"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchOwnerBoard, OwnerBoardQuery } from "@/lib/marketsOwnerApi";

type BoardEvent = {
  canonical_event_id: string;
  participant_1: string;
  participant_2: string;
  state: string;
  cross_book_match_state: string;
  orientation: string;
  hardrock?: {
    side_1?: { american?: number | null; decimal?: string | null; raw_implied?: string | null };
    side_2?: { american?: number | null; decimal?: string | null; raw_implied?: string | null };
    overround?: string | null;
    no_vig_pair?: { side_1?: string; side_2?: string } | null;
  };
  bet365?: {
    side_1?: { decimal?: string | null; raw_implied?: string | null };
    side_2?: { decimal?: string | null; raw_implied?: string | null };
    orientation?: string;
    overround?: string | null;
    no_vig_pair?: { side_1?: string; side_2?: string } | null;
  } | null;
  fanduel_coverage?: string;
  hardrock_fresh?: boolean;
  bet365_fresh?: boolean;
  observation_skew_seconds?: number | null;
  consensus_no_vig_p1?: string | null;
  m5?: { p1?: string | null; version?: string | null; hash?: string | null };
  edge_hr?: string | null;
  edge_hr_no_vig?: string | null;
  edge_consensus?: string | null;
  actionability: string;
  actionability_reasons: string[];
};

const SORTS = [
  { id: "default", label: "Default ranking" },
  { id: "edge", label: "Highest edge" },
] as const;

const FILTERS = [
  { id: "all", label: "All" },
  { id: "live", label: "Live" },
  { id: "upcoming", label: "Upcoming" },
  { id: "actionable", label: "Actionable" },
  { id: "watch", label: "Watch" },
  { id: "no-comparison", label: "No comparison" },
  { id: "unmatched", label: "Unmatched" },
  { id: "stale", label: "Stale" },
] as const;

function pct(value?: string | null): string {
  if (value == null || value === "UNKNOWN") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function american(value?: number | null): string {
  if (value == null) return "—";
  return value > 0 ? `+${value}` : String(value);
}

function stateClass(state: string): string {
  switch (state) {
    case "ACTIONABLE":
      return "dm-chip-on";
    case "WATCH":
      return "dm-chip-warn";
    default:
      return "dm-chip-muted";
  }
}

export function OwnerLiveTTBoard() {
  const [events, setEvents] = useState<BoardEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [sort, setSort] = useState<string>("default");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const load = useCallback(async () => {
    const query: OwnerBoardQuery = { sort };
    if (filter === "live") query.state = "LIVE";
    if (filter === "upcoming") query.state = "UPCOMING";
    if (filter === "actionable") query.actionability = "ACTIONABLE";
    if (filter === "watch") query.actionability = "WATCH";
    if (filter === "no-comparison") query.actionability = "NO_COMPARISON";
    if (filter === "unmatched") query.actionability = "UNMATCHED";
    if (filter === "stale") query.actionability = "STALE";
    try {
      const data = await fetchOwnerBoard(query);
      setEvents(data.events as BoardEvent[]);
      setError(null);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "board unavailable");
    } finally {
      setLoading(false);
    }
  }, [filter, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const timer = setInterval(() => void load(), 30000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <section className="dm-panel">
      <div className="dm-panel-head">
        <span className="dm-eyebrow">Table Tennis · Live decision board</span>
        <div className="board-controls">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
            {FILTERS.map((f) => (
              <option key={f.id} value={f.id}>{f.label}</option>
            ))}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            {SORTS.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          {lastUpdated ? <span className="markets-note">Updated {lastUpdated}</span> : null}
        </div>
      </div>

      {error ? (
        <div className="dm-empty"><p className="markets-note">{error}</p></div>
      ) : loading ? (
        <div className="dm-empty"><p className="markets-note">Loading board…</p></div>
      ) : events && events.length === 0 ? (
        <div className="dm-empty">
          <p className="markets-note">No current Table Tennis events. Hard Rock board may be empty right now.</p>
        </div>
      ) : events ? (
        <div className="tt-board-table" role="table" aria-label="Table Tennis board">
          <div className="tt-board-row tt-board-head" role="row">
            <span role="columnheader">Match</span>
            <span role="columnheader">Hard Rock</span>
            <span role="columnheader">Bet365</span>
            <span role="columnheader">M5</span>
            <span role="columnheader">Consensus</span>
            <span role="columnheader">Edge</span>
            <span role="columnheader">State</span>
          </div>
          {events.map((e) => (
            <Link key={e.canonical_event_id} href={`/markets/sports/${encodeURIComponent(e.canonical_event_id)}`} className="tt-board-row" role="row">
              <span role="cell" className="tt-board-match">
                <span className="tt-board-players">{e.participant_1} vs {e.participant_2}</span>
                <span className="tt-board-sub">{e.state} · {e.cross_book_match_state}</span>
              </span>
              <span role="cell">
                <span className="tt-board-odds">
                  {american(e.hardrock?.side_1?.american)} / {american(e.hardrock?.side_2?.american)}
                </span>
                <span className="tt-board-sub">implied {pct(e.hardrock?.side_1?.raw_implied)}</span>
              </span>
              <span role="cell">
                {e.bet365 ? (
                  <>
                    <span className="tt-board-odds">{e.bet365.side_1?.decimal} / {e.bet365.side_2?.decimal}</span>
                    <span className="tt-board-sub">ov {e.bet365.orientation}</span>
                  </>
                ) : (
                  <span className="tt-board-sub">{e.fanduel_coverage ?? "no comparison"}</span>
                )}
              </span>
              <span role="cell">
                <span className="tt-board-odds">{pct(e.m5?.p1)}</span>
              </span>
              <span role="cell">
                <span className="tt-board-odds">{pct(e.consensus_no_vig_p1)}</span>
              </span>
              <span role="cell">
                <span className={`tt-board-edge${(e.edge_hr ?? "").startsWith("-") ? " neg" : ""}`}>{e.edge_hr ?? "—"}</span>
              </span>
              <span role="cell">
                <span className={`dm-chip ${stateClass(e.actionability)}`}>{e.actionability}</span>
              </span>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}
