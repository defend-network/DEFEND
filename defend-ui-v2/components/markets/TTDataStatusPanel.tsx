"use client";

import { useEffect, useState } from "react";
import {
  MarketsApiError,
  TTDataStatusResponse,
  fetchTTDataStatus,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

function chipClass(ok: boolean): string {
  return ok ? "markets-on" : "markets-off";
}

function statusClass(status?: string | null): string {
  if (status === "HEALTHY") return "markets-on";
  if (status === "UNCONFIGURED") return "markets-chip-unavailable";
  if (status === "UNREGISTERED" || status === "NOT_POLLED") return "markets-chip-stale";
  return "markets-off";
}

export function TTDataStatusPanel() {
  const [state, setState] = useState<LoadState<TTDataStatusResponse>>({
    kind: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    fetchTTDataStatus()
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

  if (state.kind === "loading") {
    return <p className="markets-note">Loading TT data status...</p>;
  }
  if (state.kind === "unavailable") {
    return (
      <section className="markets-panel">
        <h2>TT DATA</h2>
        <p className="markets-note">Unavailable: {state.reason}.</p>
      </section>
    );
  }

  const { key, results_feed, odds_feed, model_history } = state.data;
  return (
    <section className="markets-panel">
      <h2>TT DATA</h2>
      <ul className="markets-list">
        <li>
          <span className="markets-key">Odds feed (the_odds_api)</span>{" "}
          <span className={statusClass(odds_feed.status)}>
            {key.configured ? (odds_feed.status ?? "NOT_POLLED") : "UNCONFIGURED"}
          </span>
          {typeof odds_feed.live_events === "number" ? (
            <span className="markets-dim"> — {odds_feed.live_events} live events</span>
          ) : null}
        </li>
        <li>
          <span className="markets-key">Results feed (the_odds_api_tt)</span>{" "}
          <span className={statusClass(results_feed.status)}>
            {key.configured ? (results_feed.status ?? "UNREGISTERED") : "UNCONFIGURED"}
          </span>
          {results_feed.last_error ? (
            <span className="markets-dim"> ({results_feed.last_error})</span>
          ) : null}
        </li>
        <li>
          <span className="markets-key">Completed TT matches</span>{" "}
          <span className="markets-on">{model_history.completed_matches}</span>
        </li>
        <li>
          <span className="markets-key">Players with history</span>{" "}
          <span className="markets-on">{model_history.players_with_history}</span>
        </li>
        <li>
          <span className="markets-key">Model-history readiness</span>{" "}
          <span className={chipClass(model_history.ready)}>
            {model_history.ready
              ? "READY"
              : `insufficient · ${model_history.players_over_threshold}/${model_history.min_games_per_player}-game threshold`}
          </span>
          {model_history.top_players.length > 0 ? (
            <span className="markets-dim">
              {" "}
              — top:{" "}
              {model_history.top_players
                .map((player) => `${player.participant_key} (${player.games})`)
                .join(", ")}
            </span>
          ) : null}
        </li>
      </ul>
      {!key.configured ? (
        <p className="markets-note">
          Enter <strong>THE_ODDS_API_KEY</strong> in{" "}
          <a className="markets-link" href="/setup">
            Setup &amp; Integrations → The Odds API
          </a>{" "}
          (live odds feed). Historical TT results come from the separate{" "}
          <strong>Odds-API.io</strong> card — key <strong>ODDS_API_IO_API_KEY</strong>.
          Nothing is fetched until a real key is supplied.
        </p>
      ) : (
        <p className="markets-note">
          Key present ({key.source ?? "unknown"}). Polls only consume credits when real data
          is returned — see the markets API note for quota math.
        </p>
      )}
    </section>
  );
}