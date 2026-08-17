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

export type WorkspaceData = {
  account: SessionResponse["account"];
  workspaces: WorkspaceResponse["workspaces"];
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

  return {
    account: session.account,
    workspaces,
  };
}