import { MARKETS_API_BASE } from "./marketsApi";
import { AdminSession, loadAdminSession } from "./adminAuth";

export type OwnerLoginResponse = {
  username: string;
  role: string;
  token: string;
  expires_in: number;
};

async function ownerJson<T>(path: string, init?: RequestInit): Promise<T> {
  const session = loadAdminSession();
  let response: Response;
  try {
    response = await fetch(`${MARKETS_API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(session ? { Authorization: `Bearer ${session.token}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new Error("markets owner API unreachable");
  }
  if (response.status === 401) {
    throw new Error("owner session expired");
  }
  if (!response.ok) {
    throw new Error(`markets owner API error ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function marketsOwnerLogin(username: string, password: string): Promise<OwnerLoginResponse> {
  let response: Response;
  try {
    response = await fetch(`${MARKETS_API_BASE}/api/markets/owner/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new Error("markets owner API unreachable");
  }
  if (!response.ok) {
    throw new Error(response.status === 401 ? "Invalid owner credentials" : `login failed (${response.status})`);
  }
  return (await response.json()) as OwnerLoginResponse;
}

export async function marketsOwnerLogout(): Promise<void> {
  const session = loadAdminSession();
  if (!session) return;
  try {
    await fetch(`${MARKETS_API_BASE}/api/markets/owner/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session.token}` },
    });
  } catch {
    // best-effort logout
  }
}

export function fetchOwnerOverview(): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>("/api/markets/owner/overview");
}

export function fetchOwnerLiveTT(): Promise<{ events: unknown[] }> {
  return ownerJson<{ events: unknown[] }>("/api/markets/owner/live-tt");
}

export type OwnerBoardQuery = {
  state?: string;
  actionability?: string;
  matched_only?: boolean;
  sort?: string;
  limit?: number;
};

export function fetchOwnerBoard(query: OwnerBoardQuery = {}): Promise<{ events: unknown[]; count: number; total: number }> {
  const params = new URLSearchParams();
  if (query.state) params.set("state", query.state);
  if (query.actionability) params.set("actionability", query.actionability);
  if (query.matched_only) params.set("matched_only", "true");
  if (query.sort) params.set("sort", query.sort);
  if (query.limit) params.set("limit", String(query.limit));
  const qs = params.toString();
  return ownerJson<{ events: unknown[]; count: number; total: number }>(
    `/api/markets/owner/live-tt${qs ? `?${qs}` : ""}`
  );
}

export function fetchOwnerEventDetail(canonicalEventId: string): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>(`/api/markets/owner/events/${encodeURIComponent(canonicalEventId)}`);
}

export function fetchOwnerDataHealth(): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>("/api/markets/owner/data-health");
}

export function fetchOwnerArbitrage(): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>("/api/markets/owner/arbitrage");
}

export function fetchOwnerModel(): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>("/api/markets/owner/model");
}

export function fetchOwnerJobs(): Promise<Record<string, unknown>> {
  return ownerJson<Record<string, unknown>>("/api/markets/owner/jobs");
}

export type { AdminSession };
