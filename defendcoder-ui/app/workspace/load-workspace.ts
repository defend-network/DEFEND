export type SessionResponse = {
  account: {
    username: string;
    role: "admin" | "consumer";
  };
};

export type WorkspaceResponse = {
  workspaces: Array<{
    workspace_id: string;
    name: string;
    repository_url?: string | null;
    default_branch?: string | null;
  }>;
};

export type RuntimeStatus = {
  state?: string | null;
  model?: string | null;
  alias?: string | null;
  provider?: string | null;
  context_used?: number | null;
  context_limit?: number | null;
  detail?: string | null;
};

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "partial_success"
  | "failed"
  | "cancelled";

export type RunPhase =
  | "queued"
  | "waiting_for_model"
  | "model_generating"
  | "executing_tool"
  | "waiting_for_model_after_tool"
  | "finalizing"
  | "completed"
  | "failed"
  | "cancelled";

export type RunReason =
  | "unknown"
  | "natural_completion"
  | "finalized"
  | "action_limit"
  | "step_limit"
  | "wall_clock_limit"
  | "model_timeout"
  | "model_unavailable"
  | "model_error"
  | "tool_error"
  | "user_cancel"
  | "internal_error"
  | "invalid_prompt";

export type RunRecord = {
  run_id: string;
  workspace_id: string;
  prompt: string;
  status: RunStatus;
  phase: RunPhase | null;
  reason: RunReason | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type ToolCallInfo = {
  id: string;
  name: string;
  arguments: Record<string, unknown> | null;
};

export type RunMessage = {
  seq: number;
  role: "assistant" | "tool" | "log";
  content: string | null;
  tool_call_id?: string | null;
  tool_name?: string | null;
  tool_result?: string | null;
  kind?: "terminal" | "tests" | "diff" | "log" | "file" | null;
  ok?: boolean | null;
  tool_calls?: ToolCallInfo[] | null;
  created_at: string;
};

export type RunDetail = {
  run: RunRecord;
  messages: RunMessage[];
};

export type FileEntry = {
  name: string;
  type: "file" | "directory";
};

export type FilesResponse = {
  path: string;
  kind: "file" | "directory";
  entries?: FileEntry[];
};

export type WorkspaceData = {
  account: SessionResponse["account"];
  workspaces: WorkspaceResponse["workspaces"];
  runtime: RuntimeStatus | null;
};


/**
 * Load workspace data from the DEFENDcoder API (8301) exactly the way the
 * server-rendered /workspace page must: the incoming browser session cookie
 * is forwarded explicitly because a Next.js server-component fetch does NOT
 * carry cookies automatically. Without this the SSR request arrives at the
 * API unauthenticated and the page renders "Session required".
 */
export async function loadWorkspaceData(
  fetchImpl: typeof fetch,
  cookieHeader: string | null,
  base: string
): Promise<WorkspaceData | null> {
  const headers: Record<string, string> = {};

  if (cookieHeader) {
    headers.cookie = cookieHeader;
  }

  const sessionResponse = await fetchImpl(
    `${base}/v1/auth/session`,
    {
      cache: "no-store",
      headers,
    }
  );

  if (!sessionResponse.ok) {
    return null;
  }

  const session = (await sessionResponse.json()) as SessionResponse;

  const workspaceResponse = await fetchImpl(
    `${base}/v1/workspaces`,
    {
      cache: "no-store",
      headers,
    }
  );

  const workspaces = workspaceResponse.ok
    ? ((await workspaceResponse.json()) as WorkspaceResponse).workspaces
    : [];

  let runtime: RuntimeStatus | null = null;

  try {
    const runtimeResponse = await fetchImpl(
      `${base}/v1/runtime/status`,
      {
        cache: "no-store",
        headers,
      }
    );

    if (runtimeResponse.ok) {
      const body = (await runtimeResponse.json()) as {
        runtime?: RuntimeStatus | null;
      };
      runtime = body.runtime ?? null;
    }
  } catch {
    runtime = null;
  }

  return {
    account: session.account,
    workspaces,
    runtime,
  };
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function apiFetch(
  fetchImpl: typeof fetch,
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const response = await fetchImpl(path, {
    credentials: "include",
    ...options,
  });

  if (!response.ok) {
    let detail = `request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string" && body.detail) {
        detail = body.detail;
      }
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, detail);
  }

  return response;
}

export async function createRun(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  prompt: string,
  csrfToken: string | null
): Promise<RunRecord> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      body: JSON.stringify({ prompt }),
    }
  );
  const body = (await response.json()) as { run: RunRecord };
  return body.run;
}

export async function fetchRunDetail(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<RunDetail> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}`
  );
  return (await response.json()) as RunDetail;
}

export async function listRuns(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string
): Promise<RunRecord[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs`
  );
  const body = (await response.json()) as { runs: RunRecord[] };
  return body.runs;
}

export async function listFiles(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  path: string
): Promise<FilesResponse> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/files?path=${encodeURIComponent(path)}`
  );
  return (await response.json()) as FilesResponse;
}

export type RunRouting = {
  requested_mode: string;
  selected_tier: string;
  selected_model: string;
  selected_provider: string | null;
  route_reason: string | null;
  escalated_from: string | null;
  escalation_approved_at: string | null;
  escalation_approved_by: string | null;
};

export type ModelTargetPublic = {
  tier: string;
  alias: string;
  provider: string;
  model: string;
  runtime_kind: string;
  requires_external_runtime: boolean;
  available: boolean;
  cost_class: string;
};

export type RoutingResponse = {
  identity: string;
  routing: RunRouting | null;
  targets: Record<string, ModelTargetPublic>;
  runtime: { state?: string | null; model?: string | null; instance_id?: number | null };
};

export type EscalationProposal = {
  proposal_id: string;
  from_model: string;
  to_model: string;
  reason_code: string;
  human_summary: string;
  evidence: string[];
  attempt_count: number;
  tests_failed: number;
  estimated_incremental_cost: string | null;
  target_runtime_state: string;
  requires_gpu_resume: boolean;
  status: string;
  created_at: string | null;
  expires_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
};

export async function fetchRouting(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<RoutingResponse> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/routing`
  );
  return (await response.json()) as RoutingResponse;
}

export async function selectModel(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string,
  requestedMode: string,
  csrfToken: string | null
): Promise<RunRouting> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/model`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      },
      body: JSON.stringify({ requested_mode: requestedMode }),
    }
  );
  const body = (await response.json()) as { routing: RunRouting };
  return body.routing;
}

export async function fetchEscalations(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<EscalationProposal[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/escalation`
  );
  const body = (await response.json()) as { proposals: EscalationProposal[] };
  return body.proposals;
}

export async function approveEscalation(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string,
  proposalId: string,
  csrfToken: string | null
): Promise<RunRouting> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/escalation/${proposalId}/approve`,
    {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    }
  );
  const body = (await response.json()) as { routing: RunRouting };
  return body.routing;
}

export async function denyEscalation(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string,
  proposalId: string,
  csrfToken: string | null
): Promise<void> {
  await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/escalation/${proposalId}/deny`,
    {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    }
  );
}

export async function sendChat(
  fetchImpl: typeof fetch,
  base: string,
  message: string,
  csrfToken: string | null
): Promise<{ reply: string; model: string; provider: string; tier: string }> {
  const response = await apiFetch(fetchImpl, `${base}/v1/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
    body: JSON.stringify({ message }),
  });
  return (await response.json()) as {
    reply: string;
    model: string;
    provider: string;
    tier: string;
  };
}

export type FileContentResponse = {
  path: string;
  binary: boolean;
  content: string | null;
  size: number;
};

export async function fetchFileContent(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  path: string
): Promise<FileContentResponse> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(path)}`
  );
  return (await response.json()) as FileContentResponse;
}

export type GitStatusResponse = {
  is_repo: boolean;
  status: string;
  unstaged_diff: string;
  staged_diff: string;
  unstaged_diff_truncated?: boolean;
  staged_diff_truncated?: boolean;
  untracked: string[];
  conflicts: string[];
  staged_count: number;
  unstaged_count: number;
  dirty: boolean;
  error?: string;
};

export async function fetchGitStatus(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string
): Promise<GitStatusResponse> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/git/status`
  );
  return (await response.json()) as GitStatusResponse;
}

export type AttemptRecord = {
  attempt_id: string;
  checkpoint_revision: number | null;
  summary: string;
  failure_class: string | null;
  relevant_files: string[];
  test_summary: string | null;
  tool_refs: string[];
  state: string;
};

export type CheckpointRecord = {
  checkpoint_id: string;
  revision: number;
  objective: string;
  current_task: string | null;
  completed_work: string[];
  current_failure: string | null;
  relevant_files: string[];
  latest_tests: string[];
  provider: string;
  model: string;
  identity_version: string;
  prompt_core_version: string;
  technical_profile_version: string;
};

export type ToolExecution = {
  execution_id: string;
  tool_call_id: string;
  tool_name: string;
  argument_hash: string;
  mutation_class: string;
  state: string;
  result_ref: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type ModelCall = {
  step: number;
  phase: string;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  finish_reason: string | null;
  tool_calls_requested: number;
  request_roundtrip_seconds: number;
  tokens_per_second: number | null;
};

export async function fetchRunAttempts(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<AttemptRecord[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/attempts`
  );
  const body = (await response.json()) as { attempts: AttemptRecord[] };
  return body.attempts;
}

export async function fetchRunCheckpoints(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<CheckpointRecord[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/checkpoints`
  );
  const body = (await response.json()) as { checkpoints: CheckpointRecord[] };
  return body.checkpoints;
}

export async function fetchRunToolExecutions(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<ToolExecution[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/tool-executions`
  );
  const body = (await response.json()) as { tool_executions: ToolExecution[] };
  return body.tool_executions;
}

export async function fetchRunTelemetry(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string
): Promise<ModelCall[]> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/telemetry`
  );
  const body = (await response.json()) as { model_calls: ModelCall[] };
  return body.model_calls;
}

export async function resumeRun(
  fetchImpl: typeof fetch,
  base: string,
  workspaceId: string,
  runId: string,
  csrfToken: string | null
): Promise<RunRecord> {
  const response = await apiFetch(
    fetchImpl,
    `${base}/v1/workspaces/${workspaceId}/runs/${runId}/resume`,
    {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
    }
  );
  const body = (await response.json()) as { run: RunRecord };
  return body.run;
}