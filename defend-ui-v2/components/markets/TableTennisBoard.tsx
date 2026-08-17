"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  MarketsApiError,
  TableTennisBoardResponse,
  TTBoardEvent,
  fetchTableTennisBoard,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

function pct(value?: string | number | null, digits = 2): string | null {
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return `${(n * 100).toFixed(digits)}%`;
}

function timeAgo(iso?: string | null): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return null;
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function legScore(event: TTBoardEvent): string {
  const withOdds = event.legs.filter((leg) => leg.decimal_odds != null);
  if (withOdds.length === 0) return "no odds quoted";
  return withOdds.map((leg) => `${leg.selection_key} ${leg.decimal_odds}`).join(" · ");
}

function liveSummary(event: TTBoardEvent): string | null {
  const state = event.live?.state;
  if (!state) return null;
  const parts: string[] = [];
  if (Array.isArray(state.sets)) parts.push(`Sets ${state.sets.join("-")}`);
  if (Array.isArray(state.points)) parts.push(`Pts ${state.points.join("-")}`);
  if (Array.isArray(state.games)) parts.push(`Games ${state.games.join("-")}`);
  if (typeof state.server === "string") parts.push(`Server ${state.server}`);
  if (typeof state.status === "string") parts.push(state.status);
  return parts.length ? parts.join(" · ") : null;
}

export function TableTennisBoard() {
  const [state, setState] = useState<LoadState<TableTennisBoardResponse>>({
    kind: "loading",
  });
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await fetchTableTennisBoard();
      setState({ kind: "ready", data });
    } catch (error) {
      setState({
        kind: "unavailable",
        reason:
          error instanceof MarketsApiError
            ? error.status === 0
              ? "markets API unreachable"
              : `markets API error ${error.status}`
            : "markets API unreachable",
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchTableTennisBoard()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            kind: "unavailable",
            reason:
              error instanceof MarketsApiError
                ? error.status === 0
                  ? "markets API unreachable"
                  : `markets API error ${error.status}`
                : "markets API unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      void load();
    }, 60_000);
    return () => clearInterval(timer);
  }, [load]);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  if (state.kind === "loading") {
    return <p className="markets-note">Loading the Table Tennis decision board...</p>;
  }
  if (state.kind === "unavailable") {
    return (
      <section className="dm-panel">
        <h2>Table Tennis</h2>
        <p className="markets-note">
          Board unavailable: {state.reason}. Live odds are only shown when the DEFENDmarkets API answers.
        </p>
      </section>
    );
  }

  const { events, provider_health, strategy_key, market_key, now } = state.data;
  const evaluated = events.filter((event) => event.decision != null).length;
  const opportunities = events.filter(
    (event) => event.decision?.decision_type === "OPPORTUNITY"
  ).length;

  return (
    <div className="dm-board">
      <section className="dm-hero">
        <div className="dm-hero-copy">
          <span className="dm-eyebrow">Sports desk · live decision support</span>
          <h1>Table Tennis Intelligence</h1>
          <p>
            Two-way {market_key} arbitrage across books. Every value on this board is
            read from live Sports database state — nothing is fabricated.
          </p>
        </div>
        <div className="dm-hero-meta">
          <span className="dm-chip">
            strategy {strategy_key} · {state.data.events[0]?.strategy.lifecycle ?? "registered"}
          </span>
          <span className="dm-chip dm-chip-muted">as of {timeAgo(now) ?? "now"}</span>
          <button
            type="button"
            className="dm-refresh"
            onClick={() => void refresh()}
            disabled={refreshing}
          >
            <RefreshCw size={14} /> {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      <section className="dm-kpis" aria-label="Board summary">
        <div className="dm-kpi">
          <span className="dm-kpi-k">Live matches</span>
          <span className="dm-kpi-v">{events.length}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Evaluated</span>
          <span className="dm-kpi-v">{evaluated}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Opportunities</span>
          <span className="dm-kpi-v dm-kpi-opp">{opportunities}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Providers</span>
          <span className="dm-kpi-v">
            {provider_health.filter((p) => p.status === "HEALTHY").length}/{provider_health.length}
          </span>
        </div>
      </section>

      {events.length === 0 ? (
        <section className="dm-panel">
          <h2>No table tennis events</h2>
          <p className="markets-note">
            No live table tennis fixtures are present in the Sports database yet. The
            board will populate as soon as the feed pipeline records events.
          </p>
        </section>
      ) : (
        <div className="dm-match-list">
          {events.map((event) => (
            <MatchCard key={event.event_key} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function MatchCard({ event }: { event: TTBoardEvent }) {
  const live = liveSummary(event);
  const freshness = event.freshness;
  const costTotal = event.costs.total;
  const netEdge = event.net_edge;
  const grossPct = pct(event.gross_edge, 3);
  const costPct = pct(costTotal, 3);
  const netPct = pct(netEdge, 3);
  const confPct = pct(event.confidence, 0);
  const qualityPct = pct(event.data_quality, 0);
  const impliedTotal = event.legs
    .map((leg) => Number(leg.implied_probability))
    .filter((n) => Number.isFinite(n));
  const impliedSum =
    impliedTotal.length >= 2
      ? `${(impliedTotal.reduce((a, b) => a + b, 0) * 100).toFixed(2)}%`
      : null;

  return (
    <article className="dm-match">
      <header className="dm-match-head">
        <div>
          <h3>{event.display_name ?? event.event_key}</h3>
          <p className="dm-match-sub">
            {event.event_key}
            {event.league_key ? ` · ${event.league_key}` : ""}
            {event.scheduled_at ? ` · scheduled ${timeAgo(event.scheduled_at)}` : ""}
          </p>
        </div>
        <DecisionBadge decision={event.decision} />
      </header>

      <div className="dm-match-grid">
        <div className="dm-cell">
          <span className="dm-cell-k">Live state</span>
          {live ? (
            <span className="dm-cell-v dm-live">
              {live}
              <small className="dm-cell-sub">
                as of {timeAgo(event.live?.observed_at) ?? "unknown"}
              </small>
            </span>
          ) : (
            <span className="dm-cell-v dm-cell-na" title="The markets board does not expose live score state yet">
              live score not wired
              <small className="dm-cell-sub">feed adapter pending</small>
            </span>
          )}
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Quotes · {event.market_key}</span>
          <span className="dm-cell-v dm-quotes">{legScore(event)}</span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Market implied</span>
          <span className="dm-cell-v">
            {impliedSum ?? "—"}
            <small className="dm-cell-sub">1/odds per leg</small>
          </span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Model probability</span>
          <span className="dm-cell-v dm-cell-na" title="tt_two_way_arb is a deterministic arb strategy; no probability model is wired">
            not wired
            <small className="dm-cell-sub">arb strategy</small>
          </span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Gross edge</span>
          <span className={`dm-cell-v${grossPct ? " dm-edge" : " dm-cell-na"}`}>
            {grossPct ?? "—"}
            <small className="dm-cell-sub">1 − ∑ implied</small>
          </span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Costs</span>
          <span className="dm-cell-v">
            {costPct ?? "unaccounted"}
            <small className="dm-cell-sub">
              {costTotal ? "venue-supplied" : "no venue cost model yet"}
            </small>
          </span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Net edge</span>
          <span className={`dm-cell-v${netPct ? " dm-edge" : " dm-cell-na"}`}>
            {netPct ?? "unaccounted"}
            <small className="dm-cell-sub">gross − costs</small>
          </span>
        </div>

        <div className="dm-cell">
          <span className="dm-cell-k">Confidence</span>
          <span className="dm-cell-v">
            {confPct ?? "—"}
            <small className="dm-cell-sub">
              {event.confidence == null
                ? "strategy ineligible"
                : "provenance-based · calibration pending outcomes"}
            </small>
          </span>
        </div>
      </div>

      <div className="dm-match-footer">
        <span className="dm-chip">
          data quality{" "}
          <strong>
            {qualityPct ?? "—"}
          </strong>
        </span>
        <span
          className={`dm-chip dm-chip-${freshness.status.toLowerCase()}`}
          title={
            freshness.age_seconds != null
              ? `oldest quoted odds ${Math.round(freshness.age_seconds / 60)}m old`
              : "no timestamped odds observed"
          }
        >
          {freshness.status === "HEALTHY"
            ? "fresh"
            : freshness.status === "STALE"
              ? `stale · ${Math.round((freshness.age_seconds ?? 0) / 60)}m`
              : "no freshness data"}
        </span>
        <span
          className={`dm-chip${event.strategy.eligible ? " dm-chip-on" : " dm-chip-warn"}`}
        >
          strategy {event.strategy.eligible ? "eligible" : `blocked · ${event.strategy.reasons?.join(", ") ?? "?"}`}
        </span>
        {event.decision?.created_at && (
          <span className="dm-chip dm-chip-muted">
            decided {timeAgo(event.decision.created_at)}
          </span>
        )}
      </div>
    </article>
  );
}

function DecisionBadge({
  decision,
}: {
  decision: TTBoardEvent["decision"];
}) {
  if (!decision) {
    return <span className="dm-badge dm-badge-none">not yet evaluated</span>;
  }
  if (decision.decision_type === "OPPORTUNITY") {
    return (
      <span className="dm-badge dm-badge-opp" title={decision.thesis ?? undefined}>
        OPPORTUNITY
        <small>{pct(decision.estimated_edge, 3) ?? "edge unknown"}</small>
      </span>
    );
  }
  return (
    <span className="dm-badge dm-badge-na" title={decision.reason_codes?.join(", ")}>
      NO_ACTION
      <small>{decision.reason_codes?.join(" · ") ?? "not actionable"}</small>
    </span>
  );
}