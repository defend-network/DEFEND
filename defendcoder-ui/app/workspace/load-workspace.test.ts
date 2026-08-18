import { describe, expect, it, vi } from "vitest";

import {
  createRun,
  fetchRunDetail,
  listFiles,
  listRuns,
  loadWorkspaceData,
  type WorkspaceResponse,
} from "@/app/workspace/load-workspace";


const BASE = "http://127.0.0.1:8301";

const SESSION_COOKIE =
  "defendcoder_session=abc123; HttpOnly; SameSite=Lax; Path=/";


function jsonResponse(
  body: unknown,
  ok = true,
  status = 200
): Response {
  const response = new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
  if (!ok) {
    Object.defineProperty(response, "ok", { value: false });
  }
  return response;
}


function loginResponse(cookieHeader: string): Response {
  const response = jsonResponse({
    account: { username: "consumer", role: "consumer" },
    csrf_token: "csrf-token-value",
  });
  response.headers.set("set-cookie", cookieHeader);
  return response;
}


describe("workspace SSR session continuity", () => {
  it("login issues a session cookie that the workspace data loader forwards", async () => {
    const login = loginResponse(SESSION_COOKIE);

    const cookiePair = login.headers.get("set-cookie")?.split(";")[0];
    expect(cookiePair).toBe("defendcoder_session=abc123");

    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).endsWith("/v1/auth/session")) {
          return jsonResponse({
            account: { username: "consumer", role: "consumer" },
          });
        }
        if (String(url).endsWith("/v1/workspaces")) {
          return jsonResponse({ workspaces: [] } satisfies WorkspaceResponse);
        }
        return jsonResponse({ error: "unexpected" }, false, 404);
      }
    );

    const data = await loadWorkspaceData(fetchMock, cookiePair ?? null, BASE);

    expect(data).not.toBeNull();
    expect(data?.account.username).toBe("consumer");

    const sessionCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/v1/auth/session")
    );
    expect(sessionCall).toBeDefined();
    const options = sessionCall?.[1] as RequestInit | undefined;
    expect(options?.headers).toMatchObject({
      cookie: "defendcoder_session=abc123",
    });
  });

  it("renders null (Session required fallback) when the API rejects the SSR fetch", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response('{"detail":"invalid session"}', {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    });

    const data = await loadWorkspaceData(fetchMock, null, BASE);

    expect(data).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/v1/auth/session`,
      expect.objectContaining({
        cache: "no-store",
        headers: {},
      })
    );
  });

  it("does not move the session token into client-visible storage or payloads", async () => {
    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).endsWith("/v1/auth/session")) {
          return jsonResponse({
            account: { username: "consumer", role: "consumer" },
          });
        }
        return jsonResponse({ workspaces: [] } satisfies WorkspaceResponse);
      }
    );

    const data = await loadWorkspaceData(
      fetchMock,
      "defendcoder_session=abc123",
      BASE
    );

    const serialized = JSON.stringify(data);
    expect(serialized).not.toContain("defendcoder_session");
    expect(serialized).not.toContain("abc123");

    const calls = JSON.stringify(fetchMock.mock.calls);
    expect(calls).not.toContain("localStorage");
    expect(calls).not.toContain("sessionStorage");
  });

  it("loads the consumer-safe runtime status alongside workspace data", async () => {
    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).endsWith("/v1/auth/session")) {
          return jsonResponse({
            account: { username: "consumer", role: "consumer" },
          });
        }
        if (String(url).endsWith("/v1/runtime/status")) {
          return jsonResponse({
            application_id: "coder",
            runtime: {
              state: "not_connected",
              model: null,
              provider: null,
            },
          });
        }
        return jsonResponse({ workspaces: [] } satisfies WorkspaceResponse);
      }
    );

    const data = await loadWorkspaceData(fetchMock, null, BASE);

    expect(data?.runtime).toEqual({
      state: "not_connected",
      model: null,
      provider: null,
    });

    const runtimeCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/v1/runtime/status")
    );
    expect(runtimeCall).toBeDefined();
    const options = runtimeCall?.[1] as RequestInit | undefined;
    expect(options).toMatchObject({
      cache: "no-store",
    });
  });

  it("forwards the session cookie on the runtime status fetch", async () => {
    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).endsWith("/v1/auth/session")) {
          return jsonResponse({
            account: { username: "consumer", role: "consumer" },
          });
        }
        if (String(url).endsWith("/v1/runtime/status")) {
          return jsonResponse({
            application_id: "coder",
            runtime: { state: "ready" },
          });
        }
        return jsonResponse({ workspaces: [] } satisfies WorkspaceResponse);
      }
    );

    await loadWorkspaceData(fetchMock, "defendcoder_session=abc123", BASE);

    const runtimeCall = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/v1/runtime/status")
    );
    expect(runtimeCall).toBeDefined();
    const options = runtimeCall?.[1] as RequestInit | undefined;
    expect(options?.headers).toMatchObject({
      cookie: "defendcoder_session=abc123",
    });
  });

  it("falls back to null runtime when the runtime endpoint is unavailable", async () => {
    const fetchMock = vi.fn(
      async (url: RequestInfo | URL, _init?: RequestInit) => {
        if (String(url).endsWith("/v1/auth/session")) {
          return jsonResponse({
            account: { username: "consumer", role: "consumer" },
          });
        }
        if (String(url).endsWith("/v1/runtime/status")) {
          return jsonResponse({ detail: "invalid session" }, false, 401);
        }
        return jsonResponse({ workspaces: [] } satisfies WorkspaceResponse);
      }
    );

    const data = await loadWorkspaceData(fetchMock, null, BASE);

    expect(data).not.toBeNull();
    expect(data?.runtime).toBeNull();
  });
});

describe("DEFENDcoder agent run API helpers", () => {
  it("createRun posts the prompt with CSRF and credentials", async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({
          run: {
            run_id: "run-1",
          workspace_id: "ws-1",
          prompt: "Build it.",
          status: "running",
          error: null,
          created_at: "2026-01-01T00:00:00Z",
          finished_at: null,
          },
        })
    );

    const run = await createRun(
      fetchMock,
      BASE,
      "ws-1",
      "Build it.",
      "csrf-token"
    );

    expect(run.run_id).toBe("run-1");
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/v1/workspaces/ws-1/runs`,
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "csrf-token",
        },
      })
    );
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init!.body))).toEqual({ prompt: "Build it." });
  });

  it("createRun surfaces the API detail for conflicts", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        { detail: "an agent run is already active for this workspace" },
        false,
        409
      )
    );

    await expect(
      createRun(fetchMock, BASE, "ws-1", "Task.", null)
    ).rejects.toMatchObject({
      status: 409,
      message: "an agent run is already active for this workspace",
    });
  });

  it("fetchRunDetail returns run plus ordered messages", async () => {
    const fetchMock = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({
          run: {
            run_id: "run-1",
          workspace_id: "ws-1",
          prompt: "Build it.",
          status: "succeeded",
          error: null,
          created_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:00:05Z",
        },
        messages: [
          {
            seq: 1,
            role: "assistant",
            content: "Done.",
            tool_calls: null,
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
      })
    );

    const detail = await fetchRunDetail(
      fetchMock,
      BASE,
      "ws-1",
      "run-1"
    );

    expect(detail.run.status).toBe("succeeded");
    expect(detail.messages).toHaveLength(1);
    expect(detail.messages[0].content).toBe("Done.");
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/v1/workspaces/ws-1/runs/run-1`,
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("listRuns returns the run list", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        runs: [
          {
            run_id: "run-2",
            workspace_id: "ws-1",
            prompt: "Task.",
            status: "failed",
            error: "model unreachable",
            created_at: "2026-01-01T00:00:00Z",
            finished_at: "2026-01-01T00:00:01Z",
          },
        ],
      })
    );

    const runs = await listRuns(fetchMock, BASE, "ws-1");

    expect(runs).toHaveLength(1);
    expect(runs[0].status).toBe("failed");
  });

  it("listFiles encodes the path query", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        path: "src",
        kind: "directory",
        entries: [{ name: "app.js", type: "file" }],
      })
    );

    const files = await listFiles(fetchMock, BASE, "ws-1", "src");

    expect(files.entries).toEqual([{ name: "app.js", type: "file" }]);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/v1/workspaces/ws-1/files?path=src`,
      expect.objectContaining({ credentials: "include" })
    );
  });
});
