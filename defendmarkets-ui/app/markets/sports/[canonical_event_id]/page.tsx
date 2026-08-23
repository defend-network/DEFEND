"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchOwnerEventDetail } from "@/lib/marketsOwnerApi";

type Detail = Record<string, unknown> & {
  available?: boolean;
  participant_1?: string;
  participant_2?: string;
  state?: string;
  cross_book_match_state?: string;
  orientation?: string;
  hardrock?: {
    side_1?: { american?: number | null; decimal?: string | null; raw_implied?: string | null; observed_at?: string | null };
    side_2?: { american?: number | null; decimal?: string | null; raw_implied?: string | null; observed_at?: string | null };
    overround?: string | null;
    no_vig_pair?: { side_1?: string; side_2?: string } | null;
  };
  bet365?: Record<string, unknown> | null;
  consensus_no_vig_p1?: string | null;
  m5?: { p1?: string | null; version?: string | null; hash?: string | null };
  edge_hr?: string | null;
  edge_hr_no_vig?: string | null;
  edge_consensus?: string | null;
  actionability?: string;
  actionability_reasons?: string[];
  observation_skew_seconds?: number | null;
  hardrock_history?: unknown[];
};

function pct(v?: string | null): string {
  if (v == null || v === "UNKNOWN") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : "—";
}

export default function MarketsEventDetailPage() {
  const params = useParams();
  const id = typeof params?.canonical_event_id === "string" ? params.canonical_event_id : "";
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    fetchOwnerEventDetail(id)
      .then((d) => {
        if (!cancelled) setDetail(d as Detail);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "event detail unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="dm-board">
      <Link href="/markets/sports" className="markets-note">← Back to board</Link>
      {error ? (
        <section className="dm-panel"><p className="markets-note">{error}</p></section>
      ) : !detail ? (
        <section className="dm-panel"><p className="markets-note">Loading…</p></section>
      ) : detail.available === false ? (
        <section className="dm-panel"><p className="markets-note">Event not found or no persisted evidence.</p></section>
      ) : (
        <>
          <section className="dm-panel">
            <span className="dm-eyebrow">Match</span>
            <h1>{detail.participant_1 ?? "UNKNOWN"} vs {detail.participant_2 ?? "UNKNOWN"}</h1>
            <p className="markets-note">
              {detail.state ?? "UNKNOWN"} · match {detail.cross_book_match_state ?? "UNKNOWN"} · orientation {detail.orientation ?? "UNAVAILABLE"}
            </p>
          </section>

          <section className="dm-panel">
            <span className="dm-eyebrow">Reference price · Hard Rock</span>
            <div className="detail-grid">
              <div className="dm-kpi"><span className="dm-kpi-k">Side 1 (American)</span><span className="dm-kpi-v">{detail.hardrock?.side_1?.american ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Side 1 (decimal)</span><span className="dm-kpi-v">{detail.hardrock?.side_1?.decimal ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Side 2 (American)</span><span className="dm-kpi-v">{detail.hardrock?.side_2?.american ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Side 2 (decimal)</span><span className="dm-kpi-v">{detail.hardrock?.side_2?.decimal ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Overround</span><span className="dm-kpi-v">{detail.hardrock?.overround ?? "—"}</span></div>
            </div>
            {detail.hardrock?.no_vig_pair ? (
              <p className="markets-note">
                No-vig: {pct(detail.hardrock.no_vig_pair.side_1)} / {pct(detail.hardrock.no_vig_pair.side_2)}
              </p>
            ) : null}
          </section>

          <section className="dm-panel">
            <span className="dm-eyebrow">Model · M5</span>
            <div className="detail-grid">
              <div className="dm-kpi"><span className="dm-kpi-k">M5 p(side 1)</span><span className="dm-kpi-v">{pct(detail.m5?.p1)}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Edge vs Hard Rock</span><span className="dm-kpi-v">{detail.edge_hr ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Edge vs consensus</span><span className="dm-kpi-v">{detail.edge_consensus ?? "—"}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Consensus no-vig</span><span className="dm-kpi-v">{pct(detail.consensus_no_vig_p1)}</span></div>
            </div>
            {detail.actionability ? (
              <p className="markets-note">
                <span className="dm-chip dm-chip-muted">{detail.actionability}</span>{" "}
                {(detail.actionability_reasons ?? []).join(" · ")}
              </p>
            ) : null}
          </section>

          <section className="dm-panel">
            <span className="dm-eyebrow">Hard Rock price history</span>
            {Array.isArray(detail.hardrock_history) && detail.hardrock_history.length > 0 ? (
              <div className="history-list">
                {detail.hardrock_history.slice(0, 20).map((h, i) => {
                  const row = h as Record<string, unknown>;
                  return (
                    <div key={i} className="history-row">
                      <span>{String(row.selection_side ?? "—")}</span>
                      <span>American {String(row.american ?? "—")}</span>
                      <span>decimal {String(row.decimal ?? "—")}</span>
                      <span>ladder #{String(row.ladder_snapshot_id ?? "—")}</span>
                      <span>{String(row.observed_at ?? "—")}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="markets-note">No Hard Rock price history yet.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
