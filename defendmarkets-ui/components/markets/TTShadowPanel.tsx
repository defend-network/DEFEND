"use client";

import { useEffect, useState } from "react";
import {
  MarketsApiError,
  ShadowEventRow,
  ShadowEventsResponse,
  ShadowOverviewResponse,
  fetchShadowEvents,
  fetchShadowOverview,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

function statusClass(status: string): string {
  if (status === "PREMATCH" || status === "LIVE") return "markets-on";
  if (status === "STALE") return "markets-chip-stale";
  if (status === "UNMATCHED") return "markets-chip-unavailable";
  if (status === "AMBIGUOUS") return "markets-off";
  return "markets-dim";
}

export function TTShadowPanel() {
  const [overview, setOverview] = useState<LoadState<ShadowOverviewResponse>>({
    kind: "loading",
  });
  const [events, setEvents] = useState<LoadState<ShadowEventsResponse>>({
    kind: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    fetchShadowOverview()
      .then((data) => {
        if (!cancelled) setOverview({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setOverview({
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
    fetchShadowEvents()
      .then((data) => {
        if (!cancelled) setEvents({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setEvents({
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

  if (overview.kind === "unavailable") {
    return (
      <section className="markets-panel">
        <h2>TT SHADOW</h2>
        <p className="markets-note">Unavailable: {overview.reason}.</p>
      </section>
    );
  }

  const data = overview.kind === "ready" ? overview.data : null;
  const eventRows = events.kind === "ready" ? events.data.events : [];
  const edgeStatus =
    data?.evaluation?.market_edge_status ?? "INSUFFICIENT_SAMPLE";

  return (
    <section className="markets-panel">
      <h2>TT SHADOW</h2>
      {overview.kind === "loading" ? (
        <p className="markets-note">Loading shadow engine...</p>
      ) : (
        <>
          <ul className="markets-list">
            <li>
              <span className="markets-key">Forward events</span>{" "}
              <span className="markets-on">
                {data!.collector.events_discovered}
              </span>{" "}
              <span className="markets-dim">
                matched {data!.collector.events_matched} · ambiguous{" "}
                {data!.collector.events_ambiguous} · unmatched{" "}
                {data!.collector.events_unmatched}
              </span>
            </li>
            <li>
              <span className="markets-key">Prematch observations</span>{" "}
              <span className="markets-on">
                {data!.collector.prematch_observations}
              </span>{" "}
              <span className="markets-dim">
                · post-commence rejected{" "}
                {data!.collector.postcommence_rejected}
              </span>
            </li>
            <li>
              <span className="markets-key">Bookmakers</span>{" "}
              <span className="markets-on">
                {data!.collector.bookmakers.join(", ") || "none"}
              </span>
            </li>
            <li>
              <span className="markets-key">M5 live inference</span>{" "}
              <span className="markets-on">
                {data!.m5.available} available
              </span>{" "}
              <span className="markets-dim">
                · {data!.m5.insufficient_history} insufficient history
              </span>
            </li>
            <li>
              <span className="markets-key">Settled sample</span>{" "}
              <span className="markets-on">{data!.evaluation.n}</span>{" "}
              <span className={statusClass(edgeStatus)}>{edgeStatus}</span>
            </li>
          </ul>
          {data!.collector.stale_events > 0 ? (
            <p className="markets-note">
              {data!.collector.stale_events} event(s) with odds older than 5
              minutes — collector may be down.
            </p>
          ) : null}
        </>
      )}
      <h3>Forward events</h3>
      {events.kind === "loading" ? (
        <p className="markets-note">Loading events...</p>
      ) : eventRows.length === 0 ? (
        <p className="markets-note">No forward events yet.</p>
      ) : (
        <table className="markets-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>Commence</th>
              <th>Status</th>
              <th>Obs</th>
              <th>M5 p(A)</th>
              <th>Disagreement</th>
            </tr>
          </thead>
          <tbody>
            {eventRows.map((event: ShadowEventRow) => (
              <tr key={event.forward_event_id}>
                <td>
                  {event.player_a} vs {event.player_b}
                  <span className="markets-dim">
                    {" "}
                    · {event.competition ?? "—"}
                  </span>
                </td>
                <td className="markets-dim">
                  {event.scheduled_commence ?? "—"}
                </td>
                <td>
                  <span className={statusClass(event.status)}>
                    {event.status}
                  </span>
                </td>
                <td>{event.observation_count}</td>
                <td>
                  {event.m5_availability === "AVAILABLE"
                    ? event.m5_p_a?.toFixed(3)
                    : "—"}
                </td>
                <td className="markets-dim">
                  {event.model_market_disagreement != null
                    ? event.model_market_disagreement.toFixed(4)
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="markets-note">
        Shadow engine is read-only: no wagers are placed.{" "}
        {edgeStatus === "INSUFFICIENT_SAMPLE" ? (
          <strong>Market edge is not measured before N ≥ 100 settled matches.</strong>
        ) : (
          <strong>Pairwise measurement active — still no wagers.</strong>
        )}
      </p>
    </section>
  );
}