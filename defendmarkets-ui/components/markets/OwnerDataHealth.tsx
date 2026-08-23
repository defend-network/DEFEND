"use client";

import { useEffect, useState } from "react";
import { fetchOwnerDataHealth } from "@/lib/marketsOwnerApi";

type Health = {
  hardrock_owls?: { credential_configured?: boolean; coverage?: string; ladder_entries?: number | null; quotes_last_capture?: number; last_quote_at?: string | null; freshness?: string };
  bet365?: { coverage?: string; last_attested_at?: string | null };
  fanduel?: { coverage?: string };
  oddspapi?: { historical_odds?: string; backfill_checkpoint?: Record<string, unknown> | null };
  postgres?: { connected?: boolean; schema_version?: number | null };
  m5?: { champion?: string; artifact_hash_short?: string; prediction_count?: number };
  jobs?: Record<string, unknown>;
};

function chipClass(v?: string): string {
  switch (v) {
    case "AVAILABLE":
    case "FRESH":
    case "HEALTHY":
      return "dm-chip-on";
    case "STALE":
    case "DEGRADED":
      return "dm-chip-warn";
    default:
      return "dm-chip-muted";
  }
}

function ProviderCard({ title, eyebrow, configured, coverage, lastAt }: { title: string; eyebrow: string; configured?: boolean; coverage?: string; lastAt?: string | null }) {
  return (
    <div className="dm-panel provider-card">
      <div className="dm-panel-head">
        <span className="dm-eyebrow">{eyebrow}</span>
        <span className={`dm-chip ${chipClass(coverage)}`}>{coverage ?? "UNKNOWN"}</span>
      </div>
      <h3>{title}</h3>
      <p className="markets-note">
        Configured: {configured ? "yes" : "no"} · Last success: {lastAt ?? "none"}
      </p>
    </div>
  );
}

export function OwnerDataHealth() {
  const [data, setData] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchOwnerDataHealth()
      .then((d) => { if (!cancelled) setData(d as Health); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "unavailable"); });
    return () => { cancelled = true; };
  }, []);

  if (error) return <section className="dm-panel"><p className="markets-note">{error}</p></section>;
  if (!data) return <section className="dm-panel"><p className="markets-note">Loading data health…</p></section>;

  return (
    <div className="dm-board">
      <section className="dm-panel">
        <span className="dm-eyebrow">Provider health</span>
        <div className="provider-grid">
          <ProviderCard
            title="Hard Rock Bet (FL)"
            eyebrow="Owls Insight"
            configured={data.hardrock_owls?.credential_configured}
            coverage={data.hardrock_owls?.coverage}
            lastAt={data.hardrock_owls?.last_quote_at}
          />
          <ProviderCard title="Bet365" eyebrow="Odds-API.io" coverage={data.bet365?.coverage} lastAt={data.bet365?.last_attested_at} />
          <ProviderCard title="FanDuel" eyebrow="Odds-API.io" coverage={data.fanduel?.coverage ?? "NO_CURRENT_TT_COVERAGE"} />
          <ProviderCard title="OddsPapi" eyebrow="Supplemental / historical" coverage={data.oddspapi?.historical_odds ?? "UNKNOWN"} />
        </div>
      </section>

      <section className="dm-panel">
        <span className="dm-eyebrow">System</span>
        <div className="detail-grid">
          <div className="dm-kpi"><span className="dm-kpi-k">Postgres</span><span className="dm-kpi-v">{data.postgres?.connected ? `schema ${data.postgres.schema_version}` : "unavailable"}</span></div>
          <div className="dm-kpi"><span className="dm-kpi-k">M5 champion</span><span className="dm-kpi-v">{data.m5?.champion ?? "M5_REGULARIZED_LOGISTIC"}</span></div>
          <div className="dm-kpi"><span className="dm-kpi-k">M5 hash</span><span className="dm-kpi-v">{data.m5?.artifact_hash_short ?? ""}</span></div>
          <div className="dm-kpi"><span className="dm-kpi-k">M5 predictions</span><span className="dm-kpi-v">{data.m5?.prediction_count ?? 0}</span></div>
          <div className="dm-kpi"><span className="dm-kpi-k">Hard Rock ladder entries</span><span className="dm-kpi-v">{data.hardrock_owls?.ladder_entries ?? "—"}</span></div>
          <div className="dm-kpi"><span className="dm-kpi-k">Hard Rock quotes</span><span className="dm-kpi-v">{data.hardrock_owls?.quotes_last_capture ?? 0}</span></div>
        </div>
      </section>
    </div>
  );
}
