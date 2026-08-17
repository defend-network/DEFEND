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

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export type RunRecord = {
  run_id: string;
  workspace_id: string;
  prompt: string;
  status: RunStatus;
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