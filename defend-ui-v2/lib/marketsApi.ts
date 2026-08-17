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