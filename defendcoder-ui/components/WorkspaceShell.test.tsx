import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceShell from "./WorkspaceShell";


const EMPTY_WORKSPACES: [] = [];


type ShellProps = {
  account?: {
    username: string;
    role: "admin" | "consumer";
  };
  runtime?: WorkspaceShellRuntime;
  workspaces?: WorkspaceShellWorkspace[];
};

type WorkspaceShellRuntime = {
  state?: string | null;
  model?: string | null;
  provider?: string | null;
  context_used?: number | null;
  context_limit?: number | null;
} | null;

type WorkspaceShellWorkspace = {
  workspace_id: string;
  name: string;
  repository_url?: string | null;
  default_branch?: string | null;
};


function renderShell(overrides: ShellProps = {}) {
  return render(
    <WorkspaceShell
      account={overrides.account ?? { username: "consumer", role: "consumer" }}
      runtime={overrides.runtime ?? null}
      workspaces={overrides.workspaces ?? []}
    />
  );
}

type RouteHandler = (init?: RequestInit) => unknown;

function routedFetch(routes: Record<string, RouteHandler>) {
  const patterns = Object.keys(routes).sort(
    (left, right) => right.length - left.length
  );
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const pattern = patterns.find((key) => url.includes(key));
    if (!pattern) {
      throw new Error(`unhandled fetch: ${url}`);
    }
    const data = await routes[pattern](init);
    return {
      ok: true,
      status: 200,
      json: async () => data,
    };
  });
}

const TEST_WORKSPACES: WorkspaceShellWorkspace[] = [
  { workspace_id: "ws-1", name: "alpha" },
  { workspace_id: "ws-2", name: "beta" },
];


describe("DEFENDcoder workspace shell", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();

    sessionStorage.clear();

    Object.defineProperty(window, "location", {
      writable: true,
      value: { href: "/" },
    });
  });

  it("renders the repo-agnostic workspace navigation", () => {
    renderShell();

    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Git Repos")).toBeInTheDocument();
    expect(screen.getByText("Workspaces")).toBeInTheDocument();
  });

  it("renders execution and review panes", () => {
    renderShell();

    expect(screen.getByText("Terminal")).toBeInTheDocument();
    expect(screen.getByText("Tests")).toBeInTheDocument();
    expect(screen.getByText("Diff")).toBeInTheDocument();
    expect(screen.getByText("Logs")).toBeInTheDocument();
  });

  it("does not fabricate unavailable runtime values", () => {
    renderShell();

    expect(
      screen.getAllByText("—", { selector: "strong" }).length
    ).toBeGreaterThan(0);
    expect(screen.queryByText("?")).not.toBeInTheDocument();
  });

  it("shows admin navigation only to admins", () => {
    const { rerender } = render(
      <WorkspaceShell
        account={{
          username: "consumer",
          role: "consumer",
        }}
        runtime={null}
        workspaces={EMPTY_WORKSPACES}
      />
    );

    expect(
      screen.queryByRole("link", { name: /admin/i })
    ).not.toBeInTheDocument();

    rerender(
      <WorkspaceShell
        account={{
          username: "admin",
          role: "admin",
        }}
        runtime={null}
        workspaces={EMPTY_WORKSPACES}
      />
    );

    expect(
      screen.getByRole("link", { name: /admin/i })
    ).toBeInTheDocument();
  });

  it("renders known runtime values when provided", () => {
    renderShell({
      runtime: {
        state: "ready",
        model: "Qwen/Qwen3-Coder-Next",
        provider: "Vast.ai",
        context_used: null,
        context_limit: 32768,
      },
    });

    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(
      screen.getAllByText("Qwen/Qwen3-Coder-Next").length
    ).toBeGreaterThan(0);
    expect(screen.getByText("Vast.ai")).toBeInTheDocument();
    expect(screen.getByText(/32768/)).toBeInTheDocument();
  });

  it("renders workspace names without assuming DEFEND-specific repos", () => {
    renderShell({
      workspaces: [
        {
          workspace_id: "1",
          name: "customer-portal",
          repository_url: "https://github.com/example/customer-portal.git",
          default_branch: "main",
        },
      ],
    });

    expect(screen.getByText("customer-portal")).toBeInTheDocument();
    expect(
      screen.getByText("https://github.com/example/customer-portal.git")
    ).toBeInTheDocument();
  });

  it("creates a local project through the workspace API with CSRF", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces": async () => ({
        workspace: {
          workspace_id: "ws-1",
          name: "sandbox",
          repository_url: null,
          default_branch: null,
        },
      }),
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });

    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell();

    fireEvent.click(screen.getByRole("button", { name: "New Project" }));

    fireEvent.change(
      screen.getByLabelText("Project name"),
      { target: { value: "sandbox" } }
    );
    fireEvent.change(
      screen.getByLabelText("Local workspace root"),
      { target: { value: "C:\\DEFEND_CODER_DATA\\sandbox" } }
    );

    fireEvent.submit(
      screen.getByRole("form", { name: /new local project/i })
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/workspaces",
        expect.objectContaining({
          method: "POST",
          credentials: "include",
        })
      );
    });

    const postCall = fetchMock.mock.calls.find(
      ([url]) => String(url) === "/v1/workspaces"
    );
    expect(postCall).toBeDefined();
    const [, request] = postCall!;
    expect(request!.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-CSRF-Token": "csrf-token-value",
    });
    expect(JSON.parse(String(request!.body))).toEqual({
      name: "sandbox",
      workspace_root: "C:\\DEFEND_CODER_DATA\\sandbox",
    });

    const createdLabels = await screen.findAllByText("sandbox");
    expect(createdLabels.length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: /sandbox/ })
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("connects a repository workspace through the workspace API", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces": async () => ({
        workspace: {
          workspace_id: "ws-2",
          name: "customer-portal",
          repository_url: "https://github.com/example/customer-portal.git",
          default_branch: "main",
        },
      }),
      "/v1/workspaces/ws-2/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });

    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell();

    fireEvent.click(screen.getByRole("button", { name: "Connect Repo" }));

    fireEvent.change(
      screen.getByLabelText("Workspace name"),
      { target: { value: "customer-portal" } }
    );
    fireEvent.change(
      screen.getByLabelText("Repository URL"),
      {
        target: {
          value: "https://github.com/example/customer-portal.git",
        },
      }
    );
    fireEvent.change(
      screen.getByLabelText("Default branch"),
      { target: { value: "main" } }
    );

    fireEvent.submit(
      screen.getByRole("form", { name: /connect repository/i })
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/v1/workspaces",
        expect.objectContaining({ method: "POST" })
      );
    });

    const postCall = fetchMock.mock.calls.find(
      ([url]) => String(url) === "/v1/workspaces"
    );
    const [, request] = postCall!;
    expect(JSON.parse(String(request!.body))).toEqual({
      name: "customer-portal",
      workspace_root: ".",
      repository_url: "https://github.com/example/customer-portal.git",
      default_branch: "main",
    });
  });

  it("selecting a workspace marks it active in the agent pane", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async () => ({ runs: [] }),
      "/v1/workspaces/ws-2/runs": async () => ({ runs: [] }),
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
      "/v1/workspaces/ws-2/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderShell({ workspaces: TEST_WORKSPACES });

    fireEvent.click(screen.getByRole("button", { name: /beta/ }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /beta/ })
      ).toHaveAttribute("aria-pressed", "true");
    });
    expect(
      screen.getByRole("button", { name: /alpha/ })
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("surfaces session-expired errors from failed creates", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "csrf validation failed" }),
    });

    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "stale-csrf");

    renderShell();

    fireEvent.click(screen.getByRole("button", { name: "New Project" }));

    fireEvent.change(
      screen.getByLabelText("Project name"),
      { target: { value: "sandbox" } }
    );
    fireEvent.change(
      screen.getByLabelText("Local workspace root"),
      { target: { value: "C:\\root" } }
    );

    fireEvent.submit(
      screen.getByRole("form", { name: /new local project/i })
    );

    expect(
      await screen.findByRole("alert")
    ).toHaveTextContent("Session expired");
  });

  it("signs out through the API and returns to the login page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => ({}),
    });

    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell();

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    const [url, request] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/v1/auth/logout");
    expect(request.method).toBe("POST");
    expect(request.headers).toMatchObject({
      "X-CSRF-Token": "csrf-token-value",
    });

    expect(window.location.href).toBe("/");
    expect(sessionStorage.getItem("defendcoder_csrf")).toBeNull();
  });

  it("enables workspace-less chat when no workspace is selected", () => {
    renderShell();

    expect(
      screen.getByRole("button", { name: "Run Tests" })
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Review Changes" })
    ).toBeDisabled();

    const composer = screen.getByLabelText("Coding task");
    expect(composer).not.toBeDisabled();
    expect(
      screen.getByText(/No workspace attached — advice and coding discussion/)
    ).toBeInTheDocument();
  });

  it("explains when the model runtime is offline", () => {
    renderShell({
      runtime: { state: "offline" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    const composer = screen.getByLabelText("Coding task");
    expect(composer).toBeDisabled();
    expect(screen.getByText(/model runtime is offline/)).toBeInTheDocument();
    expect(screen.getByText("OFFLINE")).toBeInTheDocument();
  });

  it("enables the composer only when the runtime is ready", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async () => ({ runs: [] }),
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const first = renderShell({
      runtime: { state: "starting" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));
    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).toBeDisabled();
    });

    expect(screen.getByText("STARTING")).toBeInTheDocument();
    first.unmount();

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });
    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).not.toBeDisabled();
    });
  });

  it("sends a prompt and streams the run conversation and panels", async () => {
    const runId = "run-1";
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async (init) => {
        if (init && init.method === "POST") {
          return {
            run: {
              run_id: runId,
              workspace_id: "ws-1",
              prompt: "Build an ops dashboard.",
              status: "running",
              phase: "waiting_for_model",
              reason: null,
              error: null,
              created_at: "2026-01-01T00:00:00Z",
              finished_at: null,
            },
          };
        }
        return { runs: [] };
      },
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
      [`/v1/workspaces/ws-1/runs/${runId}`]: async () => ({
        run: {
          run_id: runId,
          workspace_id: "ws-1",
          prompt: "Build an ops dashboard.",
          status: "succeeded",
          phase: "completed",
          reason: "natural_completion",
          error: null,
          created_at: "2026-01-01T00:00:00Z",
          finished_at: "2026-01-01T00:00:05Z",
        },
        messages: [
          {
            seq: 1,
            role: "assistant",
            content: null,
            tool_calls: [
              {
                id: "call_1",
                name: "write_file",
                arguments: { path: "index.html", content: "<h1>Dash</h1>" },
              },
            ],
            created_at: "2026-01-01T00:00:01Z",
          },
          {
            seq: 2,
            role: "tool",
            tool_call_id: "call_1",
            tool_name: "write_file",
            tool_result: "wrote 18 bytes to index.html",
            kind: "file",
            ok: true,
            created_at: "2026-01-01T00:00:02Z",
          },
          {
            seq: 3,
            role: "tool",
            tool_call_id: "call_2",
            tool_name: "run_tests",
            tool_result: "$ npm test\nexit code 0\n1 passing",
            kind: "tests",
            ok: true,
            created_at: "2026-01-01T00:00:03Z",
          },
          {
            seq: 4,
            role: "assistant",
            content: "Built the dashboard. Tests pass.",
            tool_calls: null,
            created_at: "2026-01-01T00:00:04Z",
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).not.toBeDisabled();
    });

    fireEvent.change(
      screen.getByLabelText("Coding task"),
      { target: { value: "Build an ops dashboard." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(
      () => {
        expect(
          screen.getByText("Built the dashboard. Tests pass.")
        ).toBeInTheDocument();
      },
      { timeout: 6000 }
    );

    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getAllByText("write_file").length).toBeGreaterThan(0);
    expect(screen.getAllByText("run_tests").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Tests" }));
    expect(
      (await screen.findAllByText(/1 passing/)).length
    ).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Diff" }));
    expect(
      screen.getByText(/Changed files in the latest run/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Terminal" }));
    expect(
      screen.getByText("No terminal output yet.")
    ).toBeInTheDocument();
  });

  it("Run Tests quick action sends the canned prompt", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async (init) => {
        if (init && init.method === "POST") {
          return {
            run: {
              run_id: "run-2",
              workspace_id: "ws-1",
              prompt: JSON.parse(String(init.body)).prompt,
              status: "succeeded",
              error: null,
              created_at: "2026-01-01T00:00:00Z",
              finished_at: "2026-01-01T00:00:01Z",
            },
          };
        }
        return { runs: [] };
      },
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Run Tests" })
      ).not.toBeDisabled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Run Tests" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/runs") && init && init.method === "POST"
      );
      expect(postCall).toBeDefined();
    });

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/runs") && init && init.method === "POST"
    )!;
    const [, request] = postCall;
    const body = JSON.parse(String(request!.body));
    expect(body.prompt).toContain("Run the workspace tests");
    expect(request!.headers).toMatchObject({
      "X-CSRF-Token": "csrf-token-value",
    });
  });

  it("surfaces honest errors when the agent is not connected", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo) => {
      const url = String(input);
      if (url.includes("/runs") && url.endsWith("/runs")) {
        return {
          ok: false,
          status: 503,
          json: async () => ({
            detail:
              "agent execution is not connected; the model runtime must be started first",
          }),
        };
      }
      if (url.includes("/runs")) {
        return { ok: true, status: 200, json: async () => ({ runs: [] }) };
      }
      if (url.includes("/files")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ path: ".", kind: "directory", entries: [] }),
        };
      }
      throw new Error(`unhandled: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).not.toBeDisabled();
    });

    fireEvent.change(
      screen.getByLabelText("Coding task"),
      { target: { value: "Do something." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByRole("alert")
    ).toHaveTextContent("Agent execution is not connected");
  });

  it("reports a conflicting run honestly", async () => {
    const fetchMock = vi.fn().mockImplementation(
      async (input: RequestInfo, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/files")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              path: ".",
              kind: "directory",
              entries: [],
            }),
          };
        }
        if (url.endsWith("/runs")) {
          if (init && init.method === "POST") {
            return {
              ok: false,
              status: 409,
              json: async () => ({
                detail: "an agent run is already active for this workspace",
              }),
            };
          }
          return { ok: true, status: 200, json: async () => ({ runs: [] }) };
        }
        throw new Error(`unhandled: ${url}`);
      }
    );
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).not.toBeDisabled();
    });

    fireEvent.change(
      screen.getByLabelText("Coding task"),
      { target: { value: "Task." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByRole("alert")
    ).toHaveTextContent("already active");
  });

  it("shows the terminal reason on a failed run", async () => {
    const failedRun = {
      run_id: "run-3",
      workspace_id: "ws-1",
      prompt: "Build it.",
      status: "partial_success",
      phase: "failed",
      reason: "action_limit",
      error: "reached the maximum of 3 agent steps",
      created_at: "2026-01-01T00:00:00Z",
      finished_at: "2026-01-01T00:00:05Z",
    };
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async (init) => {
        if (init && init.method === "POST") {
          return { run: failedRun };
        }
        return { runs: [] };
      },
      "/v1/workspaces/ws-1/runs/run-3": async () => ({
        run: failedRun,
        messages: [
          {
            seq: 1,
            role: "log",
            content:
              "reached the maximum of 3 agent steps; attempting the reserved finalization turn.",
            created_at: "2026-01-01T00:00:01Z",
          },
        ],
      }),
      "/v1/workspaces/ws-1/files": async () => ({
        path: ".",
        kind: "directory",
        entries: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    sessionStorage.setItem("defendcoder_csrf", "csrf-token-value");

    renderShell({
      runtime: { state: "ready" },
      workspaces: TEST_WORKSPACES,
    });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    await waitFor(() => {
      expect(screen.getByLabelText("Coding task")).not.toBeDisabled();
    });

    fireEvent.change(
      screen.getByLabelText("Coding task"),
      { target: { value: "Build it." } }
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByText("Partial — action limit reached")
    ).toBeInTheDocument();
  });

  it("shows the workspace file tree and navigates directories", async () => {
    const fetchMock = routedFetch({
      "/v1/workspaces/ws-1/runs": async () => ({ runs: [] }),
      "/v1/workspaces/ws-1/files?path=.": async () => ({
        path: ".",
        kind: "directory",
        entries: [
          { name: "src", type: "directory" },
          { name: "index.html", type: "file" },
        ],
      }),
      "/v1/workspaces/ws-1/files?path=src": async () => ({
        path: "src",
        kind: "directory",
        entries: [{ name: "app.js", type: "file" }],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderShell({ workspaces: TEST_WORKSPACES });

    fireEvent.click(screen.getByRole("button", { name: /alpha/ }));

    expect(await screen.findByText("index.html")).toBeInTheDocument();
    expect(screen.getByText("src/")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "src/" }));

    expect(await screen.findByText("app.js")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^↑/ })).toBeInTheDocument();
  });
});