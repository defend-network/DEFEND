import { describe, expect, it, vi } from "vitest";

import {
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
});