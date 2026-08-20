/**
 * API client for the Setup / Integrations control plane (admin-only).
 *
 * The backend is the single source of truth for provider metadata; the UI
 * renders cards from /api/admin/setup/summary and never holds business logic.
 * Raw secret values are never returned by the API — only configured/missing
 * state and a masked last-four view.
 */

export type AuthType = "api_key" | "bearer" | "user_agent" | "account" | "none";

export type AdapterKind = "real" | "placeholder";

export type ProviderState =
  | "DISABLED"
  | "PLANNED"
  | "NEEDS_CREDENTIAL"
  | "NOT_CONFIGURED"
  | "CREDENTIAL_PRESENT"
  | "ADAPTER_NOT_IMPLEMENTED"
  | "READY_TO_TEST"
  | "HEALTHY"
  | "DEGRADED"
  | "RATE_LIMITED"
  | "AUTH_FAILED"
  | "PLAN_REQUIRED"
  | "UNAVAILABLE"
  | "UNSUPPORTED_FOR_TT"
  | "CONTRACT_DRIFT"
  | "UNKNOWN";

export type HealthBadge =
  | "NOT_CONFIGURED"
  | "NOT_TESTED"
  | "HEALTHY"
  | "DEGRADED"
  | "RATE_LIMITED"
  | "UNAVAILABLE"
  | "AUTH_FAILED";

export type RateLimits = {
  requests_per_second?: number | null;
  requests_per_minute?: number | null;
  requests_per_day?: number | null;
  monthly_credits?: number | null;
};

export type ProviderLicense = {
  terms_url?: string | null;
  commercial_use_status?: string | null;
  redistribution_status?: string | null;
  attribution_requirement?: string | null;
  notes?: string | null;
};

export type CredentialState = {
  name: string;
  configured: boolean;
  masked?: string | null;
};

export type ProviderView = {
  provider_id: string;
  display_name: string;
  purpose: string;
  category: string;
  auth_type: AuthType;
  adapter_kind: AdapterKind;
  state: ProviderState;
  health_badge: HealthBadge;
  enabled: boolean;
  requires_credentials?: boolean;
  credential_configured?: boolean;
  credentials_configured?: boolean;
  test_supported?: boolean;
  credentials: CredentialState[];
  config: Record<string, string>;
  detected?: Record<string, string>;
  optional_config: string[];
  products: string[];
  docs_url?: string | null;
  host?: string | null;
  contract_version?: string | null;
  rate_limits: RateLimits;
  license: ProviderLicense;
  capabilities?: {
    live_odds?: string;
    historical_odds?: string;
    completed_results?: string;
    historical_results?: string;
    live_scores?: string;
    player_ids?: string;
    event_ids?: string;
    bookmaker_detail?: string;
    odds_movements?: string;
    multi_snapshot?: string;
    timestamped_odds?: string;
    pagination?: string;
    rate_limit?: string;
    cost_quota?: string;
    earliest_history?: string | null;
    adapter_status?: string;
    tt_live_odds?: string;
    tt_historical_odds?: string;
    tt_results?: string;
    tt_live_scores?: string;
    tt_fixtures?: string;
    tt_player_data?: string;
    tt_rankings?: string;
    tt_stats?: string;
    tt_form_h2h?: string;
    tt_live_state?: string;
    tt_bookmakers?: string;
    tt_probabilities?: string;
    tt_opening_line?: string;
    tt_closing_line?: string;
    contract_drift?: string;
    historical_odds_plan_requirement?: string | null;
  };
  tested_at?: string | null;
  last_success_at?: string | null;
  last_test_detail?: string | null;
  last_status_code?: number | null;
  last_latency_ms?: number | null;
  remaining_quota?: number | null;
  quota_reset_at?: string | null;
  last_error_class?: string | null;
  notes?: string | null;
};

export type SetupCategory = {
  category_id: string;
  display_name: string;
  description?: string | null;
  providers: ProviderView[];
};

export type SetupSummary = {
  categories: SetupCategory[];
  products: { product_id: string; display_name: string }[];
  product_providers: Record<string, string[]>;
  legacy_secret_names: string[];
  registry_secret_names: string[];
};

export type ProductMapping = {
  products: { product_id: string; display_name: string }[];
  product_providers: Record<string, string[]>;
};

export type DiagnosticRow = {
  provider_id: string;
  display_name: string;
  category: string;
  products: string[];
  auth_type: AuthType;
  adapter_kind: AdapterKind;
  implemented: boolean;
  requires_credentials?: boolean;
  credentials_configured?: boolean;
  configured?: boolean;
  enabled: boolean;
  tested?: boolean;
  state?: ProviderState;
  health_badge: HealthBadge;
  last_success_at?: string | null;
  last_test_at?: string | null;
  last_status_code?: number | null;
  last_latency_ms?: number | null;
  remaining_quota?: number | null;
  quota_reset_at?: string | null;
  detail?: string | null;
};

export type Diagnostics = { rows: DiagnosticRow[] };

export type TestResult = {
  provider_id: string;
  ok: boolean;
  badge: HealthBadge;
  detail?: string | null;
  status_code?: number | null;
  latency_ms?: number | null;
  authenticated?: boolean | null;
  remaining_quota?: number | null;
  quota_reset_at?: string | null;
  tested_at?: string | null;
};

export type TestAllResult = {
  results: TestResult[];
  tested: number;
  skipped: { provider_id: string; reason: string }[];
  summary: {
    tested: number;
    healthy: number;
    degraded: number;
    failed: number;
    skipped: number;
    planned: number;
  };
};

export type SaveSecretResult = {
  ok: boolean;
  provider_id: string;
  secret_name: string;
  configured: boolean;
  masked?: string | null;
};

const API_BASE = (process.env.NEXT_PUBLIC_DEFEND_API_BASE ?? "").replace(
  /\/$/,
  ""
);

const SETUP_TIMEOUT_MS = 90_000;
const TEST_ALL_TIMEOUT_MS = 240_000;

function adminHeaders(token: string, hasBody: boolean): HeadersInit {
  return {
    Authorization: `Bearer ${token}`,
    ...(hasBody ? { "Content-Type": "application/json" } : {}),
  };
}

async function setupJson<T>(
  token: string,
  path: string,
  init?: RequestInit,
  timeoutMs: number = SETUP_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      signal: controller.signal,
      headers: adminHeaders(token, Boolean(init?.body)),
    });
    if (!res.ok) {
      let detail = "";
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        // Non-JSON error body; keep the generic message.
      }
      if (detail) throw new Error(detail);
      throw new Error(`Request failed (${res.status})`);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Setup request timed out.");
    }
    if (err instanceof TypeError) {
      throw new Error(
        "Failed to fetch — API unreachable. Is the API server running locally?"
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function getSetupSummary(token: string): Promise<SetupSummary> {
  return setupJson<SetupSummary>(token, "/api/admin/setup/summary");
}

export function getSetupProducts(token: string): Promise<ProductMapping> {
  return setupJson<ProductMapping>(token, "/api/admin/setup/products");
}

export function getSetupDiagnostics(token: string): Promise<Diagnostics> {
  return setupJson<Diagnostics>(token, "/api/admin/setup/diagnostics");
}

export function saveSetupSecret(
  token: string,
  providerId: string,
  secretName: string,
  value: string
): Promise<SaveSecretResult> {
  return setupJson<SaveSecretResult>(
    token,
    `/api/admin/setup/providers/${encodeURIComponent(providerId)}/secret`,
    {
      method: "PUT",
      body: JSON.stringify({ secret_name: secretName, value }),
    }
  );
}

export function removeSetupSecret(
  token: string,
  providerId: string,
  secretName: string
): Promise<SaveSecretResult> {
  return setupJson<SaveSecretResult>(
    token,
    `/api/admin/setup/providers/${encodeURIComponent(providerId)}/secret?secret_name=${encodeURIComponent(secretName)}`,
    { method: "DELETE" }
  );
}

export function saveSetupConfig(
  token: string,
  providerId: string,
  update: { enabled?: boolean; config?: Record<string, string> }
): Promise<ProviderView> {
  return setupJson<ProviderView>(
    token,
    `/api/admin/setup/providers/${encodeURIComponent(providerId)}/config`,
    {
      method: "PUT",
      body: JSON.stringify(update),
    }
  );
}

export function testSetupProvider(
  token: string,
  providerId: string
): Promise<TestResult> {
  return setupJson<TestResult>(
    token,
    `/api/admin/setup/providers/${encodeURIComponent(providerId)}/test`,
    { method: "POST" }
  );
}

export function testAllSetupProviders(token: string): Promise<TestAllResult> {
  return setupJson<TestAllResult>(
    token,
    "/api/admin/setup/test-all",
    { method: "POST" },
    TEST_ALL_TIMEOUT_MS
  );
}