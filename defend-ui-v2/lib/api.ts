export type ResearchStatus =
  | "verified"
  | "partial"
  | "insufficient_evidence"
  | "direct"
  | "research"
  | "researching"
  | "error"
  | string;

export type SourceItem = {
  id: string;
  title: string;
  url?: string;
  page?: number | null;
  authority?: string | null;
};

export type ChatResponse = {
  content: string;
  research_status?: ResearchStatus | null;
  evidence_count?: number | null;
  trace_id?: string | null;
  sources?: SourceItem[];
  execution_status?: string | null;
  search_rounds?: number | null;
  recovery_attempts?: number | null;
  metadata?: Record<string, unknown> | null;
  status?: string | null;
  job_id?: string | null;
  duration_ms?: number | null;
};

const API_BASE = (process.env.NEXT_PUBLIC_DEFEND_API_BASE ?? "").replace(
  /\/$/,
  ""
);

const POLL_INTERVAL_MS = 2000;
/** Total time allowed for research poll loop */
const RESEARCH_DEADLINE_MS = 600_000; // 10 minutes
/** Per-request timeout (DIRECT answers + each poll GET) */
const DEFAULT_TIMEOUT_MS = 180_000; // 3 minutes
const POLL_TIMEOUT_MS = 60_000;
const UPLOAD_TIMEOUT_MS = 120_000;

function mergeHeaders(
  init?: RequestInit,
  jsonBody?: boolean
): HeadersInit {
  return {
    ...(jsonBody ? { "Content-Type": "application/json" } : {}),
    ...(init?.headers ?? {}),
  };
}

async function json<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: "include",
      signal: controller.signal,
      headers: mergeHeaders(init, true),
    });

    if (!res.ok) {
      throw new Error(`Request failed (${res.status})`);
    }

    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        timeoutMs >= 120_000
          ? "This reply took too long (model or network). Try a shorter question or retry."
          : "Request timed out."
      );
    }
    if (err instanceof TypeError) {
      throw new Error(
        "Failed to fetch — API unreachable or connection dropped. Is the API running?"
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function toChatResponse(data: Record<string, unknown>): ChatResponse {
  return {
    content: String(data.content ?? ""),
    research_status: (data.research_status as string) ?? null,
    evidence_count: (data.evidence_count as number) ?? null,
    trace_id: (data.trace_id as string) ?? null,
    sources: (data.sources as SourceItem[]) ?? [],
    execution_status: (data.execution_status as string) ?? null,
    search_rounds: (data.search_rounds as number) ?? null,
    recovery_attempts: (data.recovery_attempts as number) ?? null,
    metadata: (data.metadata as Record<string, unknown>) ?? null,
    status: (data.status as string) ?? "done",
    job_id: (data.job_id as string) ?? null,
  };
}

/**
 * DIRECT → full answer in one POST (up to DEFAULT_TIMEOUT_MS).
 * RESEARCH → {status:running, job_id} then poll until done (up to RESEARCH_DEADLINE_MS).
 */
export async function sendChat(
  payload: {
    message: string;
    conversation_id: string;
    document_ids: string[];
  },
  onStatus?: (label: string) => void
): Promise<ChatResponse> {
  const t0 = Date.now();

  const finish = (data: Record<string, unknown>): ChatResponse => {
    const res = toChatResponse(data);
    res.duration_ms = Date.now() - t0;
    return res;
  };

  const start = await json<Record<string, unknown>>(
    "/api/chat",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    DEFAULT_TIMEOUT_MS
  );

  if (
    start.status === "done" ||
    (typeof start.content === "string" && start.status !== "running")
  ) {
    return finish(start);
  }

  const jobId = start.job_id as string | undefined;
  if (!jobId) {
    if (start.content) return finish(start);
    throw new Error("No job_id returned for research request");
  }

  onStatus?.("Researching…");

  const deadline = Date.now() + RESEARCH_DEADLINE_MS;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    const st = await json<Record<string, unknown>>(
      `/api/chat/status/${jobId}`,
      undefined,
      POLL_TIMEOUT_MS
    );

    if (st.status === "running") {
      onStatus?.("Researching…");
      continue;
    }
    if (st.status === "error") {
      throw new Error(String(st.error || "Research job failed"));
    }
    return finish(st);
  }

  throw new Error("Research timed out after 10 minutes");
}

export async function uploadFiles(files: File[], conversationId: string) {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("conversation_id", conversationId);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

  try {
    const res = await fetch(`${API_BASE}/api/files/upload`, {
      method: "POST",
      body: form,
      credentials: "include",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`Request failed (${res.status})`);
    }
    return (await res.json()) as {
      files: Array<{ document_id: string; name: string; status: string }>;
    };
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Upload timed out.");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export type ConversationSummary = {
  conversation_id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  last_route?: string | null;
  last_model?: string | null;
  research_status?: string | null;
  message_count: number;
};

export type ConversationMessage = {
  message_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  created_at: string;
  seq: number;
  trace_id?: string | null;
  request_id?: string | null;
  metadata?: Record<string, unknown>;
};

export const listConversations = (limit = 5) =>
  json<{ conversations: ConversationSummary[] }>(`/api/conversations?limit=${Math.max(1, Math.min(limit, 5))}`);

export const createConversation = () =>
  json<{ conversation_id: string }>("/api/conversations", { method: "POST" });

export const getConversation = (conversationId: string) =>
  json<{ conversation_id: string; messages: ConversationMessage[] }>(
    `/api/conversations/${encodeURIComponent(conversationId)}`
  );

export const deleteConversation = (conversationId: string) =>
  json<{ ok: boolean }>(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
  });

export const adminHealth = (token: string) =>
  json<Record<string, unknown>>("/api/admin/system/health", {
    headers: { Authorization: `Bearer ${token}` },
  });

export const adminDocuments = (token: string) =>
  json<Record<string, unknown>>("/api/admin/rag/documents", {
    headers: { Authorization: `Bearer ${token}` },
  });

export const adminResearch = (token: string, question: string) =>
  json<Record<string, unknown>>(
    "/api/admin/research/run",
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ question }),
    },
    DEFAULT_TIMEOUT_MS
  );

export type AdminRole = "admin" | "owner";

export type ActivationStatus =
  | "pending"
  | "expired"
  | "consumed"
  | "revoked"
  | "invalid";

export type ActivationStatusResponse = {
  status: ActivationStatus;
  expires_at?: string;
  email?: string;
  display_name?: string | null;
};

export type ActivatedAccount = {
  account_id: string;
  email: string;
  display_name: string | null;
  role: "admin" | "owner" | "user";
  status: "active";
  created_at: string;
  last_access_at: string | null;
};

export type ActivateAccountResponse = {
  account: ActivatedAccount;
};

export type AdminLoginResponse = {
  username: string;
  role: AdminRole;
  token: string;
  expires_in: number;
};

function adminAuthHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}` };
}

export const adminLogin = (username: string, password: string) =>
  json<AdminLoginResponse>("/api/admin/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

export const activationStatus = (token: string) =>
  json<ActivationStatusResponse>("/api/activate/status", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export const activateAccount = (token: string, password: string) =>
  json<ActivateAccountResponse>("/api/activate", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });

export const adminLogout = (token: string) =>
  json<{ ok: boolean }>("/api/admin/logout", {
    method: "POST",
    headers: adminAuthHeaders(token),
  });

export const ttMetrics = (token: string) =>
  json<Record<string, unknown>>("/api/admin/tt/metrics", {
    headers: adminAuthHeaders(token),
  });

export const ttLive = (token: string) =>
  json<Record<string, unknown>>("/api/admin/tt/live", {
    headers: adminAuthHeaders(token),
  });

export const ttEvents = (token: string, limit = 100) =>
  json<Record<string, unknown>>(`/api/admin/tt/events?limit=${limit}`, {
    headers: adminAuthHeaders(token),
  });

export const ttAddManualMatch = (
  token: string,
  payload: Record<string, unknown>
) =>
  json<Record<string, unknown>>("/api/admin/tt/matches/manual", {
    method: "POST",
    headers: adminAuthHeaders(token),
    body: JSON.stringify(payload),
  });

export const ttEvaluate = (
  token: string,
  payload: Record<string, unknown>
) =>
  json<Record<string, unknown>>("/api/admin/tt/evaluate", {
    method: "POST",
    headers: adminAuthHeaders(token),
    body: JSON.stringify(payload),
  });

export const ttLogBet = (
  token: string,
  payload: Record<string, unknown>
) =>
  json<Record<string, unknown>>("/api/admin/tt/bets", {
    method: "POST",
    headers: adminAuthHeaders(token),
    body: JSON.stringify(payload),
  });

export const ttSettleBet = (
  token: string,
  betId: string,
  payload: Record<string, unknown>
) =>
  json<Record<string, unknown>>(`/api/admin/tt/bets/${encodeURIComponent(betId)}/settle`, {
    method: "POST",
    headers: adminAuthHeaders(token),
    body: JSON.stringify(payload),
  });
