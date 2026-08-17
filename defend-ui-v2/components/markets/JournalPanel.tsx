"use client";

import { useEffect, useState } from "react";
import {
  DecisionRow,
  MarketsApiError,
  PerformanceResponse,
  fetchDecisions,
  fetchPerformance,
} from "@/lib/marketsApi";

type LoadState<T> =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string }
  | { kind: "ready"; data: T };

function pct(value?: number | null, digits = 1): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  return `${(value * 100).toFixed(digits)}%`;
}

function money(value?: number | null): string | null {
  if (value == null || !Number.isFinite(value)) return null;
  return `${value >= 0 ? "+" : ""}$${value.toFixed(2)}`;
}

function formatTime(iso?: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return null;
  return date.toLocaleString();
}

export function JournalPanel() {
  const [performance, setPerformance] = useState<LoadState<PerformanceResponse>>({
    kind: "loading",
  });
  const [decisions, setDecisions] = useState<LoadState<DecisionRow[]>>({
    kind: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    fetchPerformance()
      .then((data) => {
        if (!cancelled) setPerformance({ kind: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setPerformance({
            kind: "unavailable",
            reason: error instanceof MarketsApiError && error.status !== 0 ? `error ${error.status}` : "unreachable",
          });
        }
      });
    fetchDecisions(100)
      .then((data) => {
        if (!cancelled) setDecisions({ kind: "ready", data: data.decisions });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setDecisions({
            kind: "unavailable",
            reason: error instanceof MarketsApiError && error.status !== 0 ? `error ${error.status}` : "unreachable",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const perf = performance.kind === "ready" ? performance.data : null;

  return (
    <div className="dm-board">
      <section className="dm-hero">
        <div className="dm-hero-copy">
          <span className="dm-eyebrow">Journal desk · append-only records</span>
          <h1>Journal &amp; Performance</h1>
          <p>
            Every evaluation is journaled with its decision type, edge and costs.
            Performance panels are computed from settled outcomes only — metrics with
            no real basis are shown as not wired, never invented.
          </p>
        </div>
      </section>

      <section className="dm-panel">
        <h2>Performance</h2>
        {performance.kind === "loading" && (
          <p className="markets-note">Loading performance from real journal rows...</p>
        )}
        {performance.kind === "unavailable" && (
          <p className="markets-note">Performance unavailable: {performance.reason}.</p>
        )}
        {perf && (
          <div className="dm-perf-grid">
            <PerfCard
              label="Net ROI"
              value={money(perf.roi.value)}
              available={perf.roi.available}
              note={perf.roi.available ? "real" : perf.roi.reason ?? "not wired"}
            />
            <PerfCard
              label="Calibration"
              value={
                perf.calibration.available
                  ? `${Object.keys(perf.calibration.buckets).length} bucket${Object.keys(perf.calibration.buckets).length === 1 ? "" : "s"}`
                  : null
              }
              available={perf.calibration.available}
              note={
                perf.calibration.available
                  ? Object.entries(perf.calibration.buckets)
                      .map(([bucket, count]) => `${bucket}: ${count}`)
                      .join(" · ")
                  : perf.calibration.reason ?? "not wired"
              }
            />
            <PerfCard
              label="CLV"
              value={pct(perf.clv.value, 3)}
              available={perf.clv.available}
              note={perf.clv.available ? "average closing line value" : perf.clv.reason ?? "not wired"}
            />
            <PerfCard
              label="Max drawdown"
              value={money(perf.max_drawdown.value)}
              available={perf.max_drawdown.available}
              note={perf.max_drawdown.available ? "from settled pnl sequence" : perf.max_drawdown.reason ?? "not wired"}
            />
            <PerfCard
              label="Sample size"
              value={`${perf.sample_size.decisions} decisions`}
              available={perf.sample_size.decisions > 0}
              note={`${perf.sample_size.opportunities} opportunities · ${perf.sample_size.settled} settled`}
            />
            <PerfCard
              label="NO_ACTION rate"
              value={pct(perf.no_action_pct)}
              available={perf.sample_size.decisions > 0}
              note={perf.sample_size.decisions > 0 ? "of all journaled decisions" : "no decisions journaled yet"}
            />
            <PerfCard
              label="Net P/L"
              value={money(perf.net_pnl)}
              available={perf.net_pnl != null}
              note={perf.net_pnl != null ? "sum of settled outcome pnl" : "no settled outcomes yet"}
            />
            <PerfCard
              label="Win rate"
              value={pct(perf.win_rate)}
              available={perf.win_rate != null}
              note={perf.win_rate != null ? "settled outcomes" : "no settled outcomes yet"}
            />
          </div>
        )}
      </section>

      <section className="dm-panel">
        <h2>Decision journal</h2>
        {decisions.kind === "loading" && <p className="markets-note">Loading journal entries...</p>}
        {decisions.kind === "unavailable" && (
          <p className="markets-note">Journal unavailable: {decisions.reason}.</p>
        )}
        {decisions.kind === "ready" && decisions.data.length === 0 && (
          <p className="markets-note">
            No decisions have been journaled yet. The journal fills in as the decision
            loop evaluates real markets.
          </p>
        )}
        {decisions.kind === "ready" && decisions.data.length > 0 && (
          <div className="dm-journal">
            {decisions.data.map((decision) => (
              <article
                key={decision.decision_id ?? String(decision.created_at)}
                className={`dm-journal-row dm-journal-${(decision.decision_type ?? "no_action").toLowerCase()}`}
              >
                <div className="dm-journal-id">
                  <strong>
                    {decision.instrument_key
                      ?.split(":")
                      .slice(1)
                      .join(" · ") ?? decision.strategy_key ?? "unknown instrument"}
                  </strong>
                  <small>{decision.thesis}</small>
                </div>
                <div className="dm-journal-metrics">
                  <span className={`dm-chip${decision.decision_type === "OPPORTUNITY" ? " dm-chip-on" : " dm-chip-warn"}`}>
                    {decision.decision_type ?? "NO_ACTION"}
                  </span>
                  {decision.estimated_edge != null && (
                    <span className="dm-chip dm-chip-muted">
                      edge {pct(Number(decision.estimated_edge), 3)}
                    </span>
                  )}
                  {decision.cost_estimate != null && (
                    <span className="dm-chip dm-chip-muted">
                      costs {pct(Number(decision.cost_estimate), 3)}
                    </span>
                  )}
                  {decision.reason_codes && decision.reason_codes.length > 0 && (
                    <span className="dm-chip dm-chip-warn">
                      {decision.reason_codes.join(" · ")}
                    </span>
                  )}
                </div>
                <div className="dm-journal-meta">
                  <span>{decision.strategy_key}@{decision.policy_key}</span>
                  {decision.created_at && <span>{formatTime(decision.created_at)}</span>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function PerfCard({
  label,
  value,
  available,
  note,
}: {
  label: string;
  value: string | null;
  available: boolean;
  note: string;
}) {
  return (
    <div className={`dm-perf${available ? " dm-perf-on" : " dm-perf-na"}`}>
      <span className="dm-perf-k">{label}</span>
      <span className="dm-perf-v">{value ?? "not wired"}</span>
      <span className="dm-perf-note" title={note}>
        {note}
      </span>
    </div>
  );
}