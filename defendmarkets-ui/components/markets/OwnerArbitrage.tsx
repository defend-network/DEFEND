"use client";

import { useEffect, useState } from "react";
import { fetchOwnerArbitrage } from "@/lib/marketsOwnerApi";

type ArbStatus = {
  current_active_arbs?: number;
  current_mathematical_arbs?: number;
  paper_arb_tickets?: number;
  quotes_current?: number;
  distinct_books?: string[];
  two_book_events?: number;
  arb_verifications?: number;
};

export function OwnerArbitrage() {
  const [data, setData] = useState<ArbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchOwnerArbitrage()
      .then((d) => { if (!cancelled) setData(d as ArbStatus); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "unavailable"); });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="dm-board">
      <section className="dm-panel">
        <span className="dm-eyebrow">Sports arbitrage</span>
        {error ? (
          <p className="markets-note">{error}</p>
        ) : !data ? (
          <p className="markets-note">Loading…</p>
        ) : (
          <>
            <div className="detail-grid">
              <div className="dm-kpi"><span className="dm-kpi-k">Active arbs</span><span className="dm-kpi-v">{data.current_active_arbs ?? 0}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Mathematical arbs</span><span className="dm-kpi-v">{data.current_mathematical_arbs ?? 0}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Paper arb tickets</span><span className="dm-kpi-v">{data.paper_arb_tickets ?? 0}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Two-book events</span><span className="dm-kpi-v">{data.two_book_events ?? 0}</span></div>
              <div className="dm-kpi"><span className="dm-kpi-k">Verifications</span><span className="dm-kpi-v">{data.arb_verifications ?? 0}</span></div>
            </div>
            {(data.current_active_arbs ?? 0) === 0 ? (
              <p className="markets-note">NO CURRENT QUALIFYING ARBITRAGE</p>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
