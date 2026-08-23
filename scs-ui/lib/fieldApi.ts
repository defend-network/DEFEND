import {api} from "./api";

export type ReadinessState = "NOT_READY" | "NEEDS_REVIEW" | "READY_WITH_NOTES" | "READY";

export type ReadinessReason = {
  key: string;
  severity: "BLOCKING" | "IMPORTANT" | "OPTIONAL";
  label: string;
  action: string;
};

export type ReadinessResult = {
  state: ReadinessState;
  readiness: string;
  reasons: ReadinessReason[];
  BLOCKING: ReadinessReason[];
  IMPORTANT: ReadinessReason[];
  OPTIONAL: ReadinessReason[];
};

export type KnowledgeStatus = {
  knowledge_root: string;
  configured: boolean;
  state: "CONFIGURED" | "NOT_CONFIGURED";
  documents: Array<Record<string, unknown>>;
  counts: Record<string, number>;
  discovered: number;
  owner_approved: number;
  indexed: number;
  blocked: number;
};

export type ChatAnswer = {
  answer_id: string;
  job_id: string;
  visible_answer: string;
  copilot_mode: string;
  verified_claims: Array<Record<string, unknown>>;
  blocked_claims: {count: number; reasons: string[]};
  citations: Array<Record<string, unknown>>;
  tool_calls: Array<Record<string, unknown>>;
  open_measurements: Array<Record<string, unknown>>;
  next_measurements: string[];
  active_procedure: string[];
  active_diagnostic: string[];
  session_durable: boolean;
  data_gaps: number | null;
  conflicts: unknown[];
  model: string | null;
  provider: string | null;
  latency_ms: number | null;
  answer_state: string;
};

export async function jobTruth(jobId: string): Promise<Record<string, unknown>> {
  return api(`/api/scs/field/jobs/${encodeURIComponent(jobId)}/truth`);
}

export async function jobReadiness(jobId: string): Promise<ReadinessResult> {
  return api<ReadinessResult>(`/api/scs/field/jobs/${encodeURIComponent(jobId)}/readiness`);
}

export async function jobChat(jobId: string, message: string): Promise<ChatAnswer> {
  return api<ChatAnswer>(`/api/scs/field/jobs/${encodeURIComponent(jobId)}/copilot/chat`, {
    method: "POST",
    body: JSON.stringify({message}),
  });
}

export async function knowledgeStatus(): Promise<KnowledgeStatus> {
  return api<KnowledgeStatus>("/api/scs/knowledge/status");
}

export async function knowledgeDiscover(): Promise<{documents: Array<Record<string, unknown>>}> {
  return api("/api/scs/knowledge/discover", {method: "POST"});
}

export async function knowledgeApprove(payload: Record<string, unknown>): Promise<{source: Record<string, unknown>}> {
  return api("/api/scs/knowledge/approve", {method: "POST", body: JSON.stringify(payload)});
}
