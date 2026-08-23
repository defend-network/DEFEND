export type DeskState = {
  available: boolean;
  status: string;
};

export type OverviewResponse = {
  application_id: string;
  counts: Record<string, number>;
  venues: number;
  provider_health: {
    ok: boolean | null;
    sources: { source_key: string; status: string }[];
  };
  desks: Record<string, DeskState>;
  pit_availability: string[];
};

export type CatalogItem = Record<string, unknown>;

export type QualityObservation = {
  quality_id?: string;
  instrument_key?: string;
  venue_key?: string;
  score?: string | number | null;
  freshness_ok?: boolean;
  availability?: string;
  as_of?: string | null;
};

export type DataHealthResponse = {
  quality_observations: QualityObservation[];
  sports_provider_health: {
    source_key: string;
    status: string;
    observed_at?: string | null;
  }[];
};

export type ProviderFeedRow = {
  provider_id?: string;
  display_name?: string | null;
  status?: string;
  last_attempt_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  latency_ms?: number | null;
  records_ingested?: number | null;
  last_record_at?: string | null;
  detail_json?: Record<string, unknown> | null;
};

export type ProviderFeedResponse = {
  providers: ProviderFeedRow[];
};

export type ProviderRecordsResponse = {
  provider_id: string;
  records: {
    record_key?: string;
    observed_at?: string | null;
    received_at?: string | null;
  }[];
};

export type TTDataStatusResponse = {
  as_of?: string;
  key: {
    configured: boolean;
    source?: string | null;
    entry_point: string;
  };
  results_feed: {
    provider_id: string;
    configured: boolean;
    status?: string | null;
    last_attempt_at?: string | null;
    last_success_at?: string | null;
    last_error?: string | null;
    records_ingested?: number | null;
  };
  odds_feed: {
    provider_id: string;
    configured: boolean;
    status?: string | null;
    last_success_at?: string | null;
    live_events?: number | null;
  };
  model_history: {
    completed_matches: number;
    players_with_history: number;
    min_games_per_player: number;
    players_over_threshold: number;
    ready: boolean;
    top_players: { participant_key: string; games: number }[];
  };
  note?: string;
};

export type TTModelDetail = {
  model?: string;
  version?: string;
  available: boolean;
  reason?: string | null;
  home_participant_key?: string | null;
  away_participant_key?: string | null;
  p_home?: string | null;
  p_away?: string | null;
  home_rating?: string | null;
  away_rating?: string | null;
  home_games?: number;
  away_games?: number;
  home_form?: string | null;
  away_form?: string | null;
  calibration_bucket?: string | null;
};

export type EvaluateResponse = {
  decision_id?: string | null;
  decision_type: "OPPORTUNITY" | "NO_ACTION";
  reason_codes?: string[];
  strategy_key?: string;
  strategy_version?: number;
  policy_key?: string;
  policy_version?: number;
  thesis?: string;
  confidence?: string | null;
  estimated_edge?: string | null;
  cost_estimate?: string | null;
  invalidation?: string | null;
  created_at?: string | null;
  opportunity_id?: string | null;
  gate?: {
    ok?: boolean;
    availability?: string;
    freshness_ok?: boolean;
    reasons?: string[];
  } | null;
};

export type DecisionRow = {
  decision_id?: string | null;
  opportunity_id?: string | null;
  strategy_key?: string;
  policy_key?: string;
  decision_type?: "OPPORTUNITY" | "NO_ACTION";
  reason_codes?: string[];
  thesis?: string;
  confidence?: string | null;
  estimated_edge?: string | null;
  cost_estimate?: string | null;
  data_cutoff_timestamp?: string | null;
  model_version?: string | null;
  created_at?: string | null;
  amendment_of?: string | null;
  outcome_id?: string | null;
  instrument_key?: string | null;
};

export type TTLeg = {
  selection_key: string;
  display_name?: string | null;
  decimal_odds?: string | null;
  implied_probability?: string | null;
  source_key?: string | null;
  observed_at?: string | null;
  received_at?: string | null;
  raw_ref?: string | null;
};

export type TTLiveState = {
  state: Record<string, unknown>;
  observed_at?: string | null;
  received_at?: string | null;
};

export type TTBoardEvent = {
  event_key: string;
  display_name?: string | null;
  scheduled_at?: string | null;
  league_key?: string | null;
  market_key: string;
  live: TTLiveState | null;
  legs: TTLeg[];
  gross_edge?: string | null;
  costs: {
    components: Record<string, string | null>;
    total?: string | null;
  };
  net_edge?: string | null;
  confidence?: string | null;
  model_probability?: string | null;
  model_probability_available: boolean;
  model?: TTModelDetail | null;
  data_quality?: string | null;
  freshness: {
    ok: boolean;
    status: "HEALTHY" | "STALE" | "UNAVAILABLE";
    age_seconds?: number | null;
  };
  strategy: {
    key: string;
    version?: number;
    lifecycle?: string;
    eligible: boolean;
    reasons?: string[];
  };
  decision: {
    decision_id?: string | null;
    decision_type?: "OPPORTUNITY" | "NO_ACTION";
    reason_codes?: string[];
    thesis?: string | null;
    estimated_edge?: string | null;
    cost_estimate?: string | null;
    confidence?: string | null;
    created_at?: string | null;
  } | null;
};

export type TableTennisBoardResponse = {
  events: TTBoardEvent[];
  provider_health: { source_key: string; status?: string }[];
  strategy_key: string;
  market_key: string;
  now: string;
};

export type PerformanceResponse = {
  sample_size: {
    decisions: number;
    opportunities: number;
    no_actions: number;
    settled: number;
  };
  no_action_pct?: number | null;
  net_pnl?: number | null;
  win_rate?: number | null;
  roi: {
    value?: number | null;
    available: boolean;
    reason?: string | null;
  };
  clv: {
    value?: number | null;
    available: boolean;
    reason?: string | null;
  };
  calibration: {
    available: boolean;
    buckets: Record<string, number>;
    reason?: string | null;
  };
  max_drawdown: {
    value?: number | null;
    available: boolean;
    reason?: string | null;
  };
  as_of?: string | null;
};

export const MARKETS_API_BASE = (
  process.env.NEXT_PUBLIC_MARKETS_API_BASE ?? "http://127.0.0.1:8300"
).replace(/\/$/, "");

export class MarketsApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${MARKETS_API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new MarketsApiError("markets API unreachable", 0);
  }
  if (!response.ok) {
    throw new MarketsApiError(`markets API error ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export function fetchOverview(): Promise<OverviewResponse> {
  return json<OverviewResponse>("/v1/overview");
}

export function fetchCatalog<T = CatalogItem>(
  collection: string,
  query: string = ""
): Promise<{ [key: string]: T[] }> {
  return json<{ [key: string]: T[] }>(`/v1/catalog/${collection}${query}`);
}

export function fetchList<T = CatalogItem>(path: string): Promise<{ [key: string]: T[] }> {
  return json<{ [key: string]: T[] }>(path);
}

export function fetchDataHealth(): Promise<DataHealthResponse> {
  return json<DataHealthResponse>("/v1/data-quality");
}

export function fetchProviders(): Promise<ProviderFeedResponse> {
  return json<ProviderFeedResponse>("/v1/providers");
}

export function fetchProviderRecords(
  providerId: string,
  limit: number = 50
): Promise<ProviderRecordsResponse> {
  return json<ProviderRecordsResponse>(
    `/v1/providers/${encodeURIComponent(providerId)}/records?limit=${limit}`
  );
}

export function fetchTableTennisBoard(): Promise<TableTennisBoardResponse> {
  return json<TableTennisBoardResponse>("/v1/sports/table-tennis");
}

export function fetchTTDataStatus(): Promise<TTDataStatusResponse> {
  return json<TTDataStatusResponse>("/v1/sports/tt/data-status");
}

export type ShadowAggregate = {
  n: number;
  m5_brier?: number | null;
  m5_log_loss?: number | null;
  market_brier?: number | null;
  market_log_loss?: number | null;
  m5_minus_market_brier?: number | null;
  market_rows?: number;
};

export type ShadowEvaluation = {
  n: number;
  thresholds: Record<string, { n: number } | null>;
  market_edge_status: string;
  pooled: ShadowAggregate;
  per_class: Record<string, ShadowAggregate>;
};

export type ShadowOverviewResponse = {
  as_of: string;
  collector: {
    events_discovered: number;
    events_matched: number;
    events_ambiguous: number;
    events_unmatched: number;
    prematch_observations: number;
    postcommence_rejected: number;
    bookmakers: string[];
    stale_events: number;
  };
  m5: { available: number; insufficient_history: number };
  evaluation: ShadowEvaluation;
};

export type ShadowEventRow = {
  forward_event_id: number;
  provider?: string | null;
  provider_event_id?: string | null;
  canonical_event_id?: string | null;
  match_level?: string | null;
  competition?: string | null;
  player_a?: string | null;
  player_b?: string | null;
  scheduled_commence?: string | null;
  status: string;
  last_odds_poll_at?: string | null;
  observation_count: number;
  last_valid_prematch_at?: string | null;
  m5_p_a?: number | null;
  m5_availability?: string | null;
  model_market_disagreement?: number | null;
};

export type ShadowEventsResponse = {
  as_of: string;
  events: ShadowEventRow[];
};

export type ShadowEvaluationResponse = {
  as_of: string;
  evaluation: ShadowEvaluation;
  recent: {
    canonical_event_id: string;
    result_id: number;
    reference_class: string;
    settled_at: string;
    m5_p_a: number;
    market_no_vig_p_a?: number | null;
    actual: number;
  }[];
};

export function fetchShadowOverview(): Promise<ShadowOverviewResponse> {
  return json<ShadowOverviewResponse>("/v1/sports/tt/shadow/overview");
}

export function fetchShadowEvents(
  limit: number = 100
): Promise<ShadowEventsResponse> {
  return json<ShadowEventsResponse>(`/v1/sports/tt/shadow/events?limit=${limit}`);
}

export function fetchShadowEvaluation(): Promise<ShadowEvaluationResponse> {
  return json<ShadowEvaluationResponse>("/v1/sports/tt/shadow/evaluation");
}

export function fetchPerformance(): Promise<PerformanceResponse> {
  return json<PerformanceResponse>("/v1/performance");
}

export function fetchDecisions(limit: number = 50): Promise<{ decisions: DecisionRow[] }> {
  return json<{ decisions: DecisionRow[] }>(`/v1/decisions?limit=${limit}`);
}

export function evaluateSports(
  eventKey: string,
  marketKey: string,
  strategyKey: string = "tt_two_way_arb",
  policyKey: string = "markets_core"
): Promise<EvaluateResponse> {
  return json<EvaluateResponse>("/v1/evaluate/sports", {
    method: "POST",
    body: JSON.stringify({
      event_key: eventKey,
      market_key: marketKey,
      strategy_key: strategyKey,
      policy_key: policyKey,
    }),
  });
}