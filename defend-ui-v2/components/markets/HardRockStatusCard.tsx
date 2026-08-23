"use client";

import { useEffect, useState } from "react";
import { fetchOwnerOverview } from "@/lib/marketsOwnerApi";

type OwnerOverview = {
  hardrock_owls?: {
    coverage?: string;
    ladder_entries?: number | null;
    quotes_last_capture?: number;
    last_quote_at?: string | null;
    freshness?: string;
  };
  bet365?: { coverage?: string };
  fanduel?: { coverage?: string };
  m5?: { champion?: string; artifact_hash_short?: string; prediction_count?: number };
  postgres?: { schema_version?: number | null };
};

function statusClass(state?: string): string {
  switch (state) {
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

export function HardRockStatusCard() {
  const [data, setData] = useState<OwnerOverview | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchOwnerOverview()
      .then((d) => {
        if (!cancelled) setData(d as OwnerOverview);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return null;
  if (!data) return null;

  const hr = data.hardrock_owls;

  return (
    <section className="dm-panel hardrock-card">
      <div className="dm-panel-head">
        <span className="dm-eyebrow">Hard Rock Bet (FL) via Owls Insight</span>
        <span className={`dm-chip ${statusClass(hr?.coverage)}`}>{hr?.coverage ?? "UNKNOWN"}</span>
      </div>
      <div className="hardrock-kpis">
        <div className="dm-kpi">
          <span className="dm-kpi-k">Quotes captured</span>
          <span className="dm-kpi-v">{hr?.quotes_last_capture ?? 0}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Ladder entries</span>
          <span className="dm-kpi-v">{hr?.ladder_entries ?? "—"}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Freshness</span>
          <span className={`dm-kpi-v dm-chip ${statusClass(hr?.freshness)}`}>{hr?.freshness ?? "UNKNOWN"}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">Bet365</span>
          <span className={`dm-kpi-v dm-chip ${statusClass(data.bet365?.coverage)}`}>{data.bet365?.coverage ?? "UNKNOWN"}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">FanDuel</span>
          <span className="dm-kpi-v dm-chip dm-chip-muted">{data.fanduel?.coverage ?? "UNKNOWN"}</span>
        </div>
        <div className="dm-kpi">
          <span className="dm-kpi-k">M5</span>
          <span className="dm-kpi-v">{data.m5?.champion ?? "M5_REGULARIZED_LOGISTIC"}</span>
        </div>
      </div>
      {data.postgres?.schema_version ? (
        <p className="markets-note">Postgres schema {data.postgres.schema_version} · M5 {data.m5?.artifact_hash_short ?? ""}</p>
      ) : null}
    </section>
  );
}
