"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  ApiError,
  approveEscalation,
  createRun,
  denyEscalation,
  EscalationProposal,
  fetchEscalations,
  fetchRunDetail,
  fetchRouting,
  FileEntry,
  listFiles,
  listRuns,
  ModelTargetPublic,
  RunDetail,
  RunMessage,
  RunRecord,
  RunRouting,
  RuntimeStatus,
  selectModel,
  sendChat,
} from "@/app/workspace/load-workspace";
import EscalationModal from "./EscalationModal";
import ModelSelector, { ModelMode } from "./ModelSelector";

type Account = {
  username: string;
  role: "admin" | "consumer";
};

type Workspace = {
  workspace_id: string;
  name: string;
  repository_url?: string | null;
  default_branch?: string | null;
};

type CreateWorkspacePayload = {
  name: string;
  workspace_root: string;
  repository_url?: string | null;
  default_branch?: string | null;
};

type Props = {
  account: Account;
  runtime: RuntimeStatus | null;
  workspaces: Workspace[];
};

type ExecutionTab = "terminal" | "tests" | "diff" | "logs";

const RUN_TESTS_PROMPT =
  "Run the workspace tests (run_tests) and report the real results. " +
  "If no test runner is detected, say so honestly and propose what to add.";

const REVIEW_CHANGES_PROMPT =
  "Review the current uncommitted changes: run git_diff, inspect the " +
  "changed files with read_file, and summarize what changed, whether it " +
  "looks correct, and any risks.";

const POLL_INTERVAL_MS = 1500;

function runtimeLabel(state: string | null | undefined): string {
  switch (state) {
    case "ready":
      return "READY";
    case "starting":
      return "STARTING";
    case "offline":
      return "OFFLINE";
    case "failed":
      return "FAILED";
    default:
      return state ? state.toUpperCase() : "—";
  }
}

function runtimeStateClass(state: string | null | undefined): string {
  switch (state) {
    case "ready":
      return "runtime-state-ready";
    case "starting":
      return "runtime-state-starting";
    case "failed":
      return "runtime-state-failed";
    default:
      return "runtime-state-offline";
  }
}

function runStatusLabel(status: RunRecord["status"]): string {
  switch (status) {
    case "queued":
      return "Queued";
    case "running":
      return "Running";
    case "succeeded":
      return "Succeeded";
    case "partial_success":
      return "Partial";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return status;
  }
}

function runReasonLabel(reason: RunRecord["reason"] | null): string | null {
  if (!reason || reason === "unknown") {
    return null;
  }
  switch (reason) {
    case "natural_completion":
      return "Completed";
    case "finalized":
      return "Completed (step limit, finalized)";
    case "action_limit":
      return "Partial — action limit reached";
    case "step_limit":
      return "Partial — step limit reached";
    case "wall_clock_limit":
      return "Partial — wall-clock limit reached";
    case "model_timeout":
      return "Failed — model timed out";
    case "model_unavailable":
      return "Failed — model unavailable";
    case "model_error":
      return "Failed — model error";
    case "tool_error":
      return "Failed — tool error";
    case "user_cancel":
      return "Cancelled";
    default:
      return reason.replaceAll("_", " ");
  }
}

function phaseLabel(phase: RunRecord["phase"] | null): string {
  switch (phase) {
    case "waiting_for_model":
    case "waiting_for_model_after_tool":
      return "Waiting for model";
    case "model_generating":
      return "Model is generating";
    case "executing_tool":
      return "Executing tool";
    case "finalizing":
      return "Finalizing";
    case "queued":
      return "Queued";
    default:
      return "Running";
  }
}

function runElapsedSeconds(run: RunRecord, now: number): number | null {
  const start = run.created_at ? Date.parse(run.created_at) : NaN;
  if (!Number.isFinite(start)) {
    return null;
  }
  const end = run.finished_at ? Date.parse(run.finished_at) : now;
  if (!Number.isFinite(end)) {
    return null;
  }
  return Math.max(0, Math.round((end - start) / 1000));
}

function display(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === ""
    ? "—"
    : String(value);
}

function csrfToken(): string | null {
  try {
    return sessionStorage.getItem("defendcoder_csrf");
  } catch {
    return null;
  }
}

function promptForRun(run: RunRecord | null | undefined): string {
  return run ? run.prompt : "";
}

function changedFileHints(messages: RunMessage[]): string[] {
  const hints: string[] = [];
  for (const message of messages) {
    if (message.role !== "assistant" || !message.tool_calls) {
      continue;
    }
    for (const call of message.tool_calls) {
      if (call.name !== "write_file" && call.name !== "edit_file") {
        continue;
      }
      const path = extractPath(call.arguments);
      if (path) {
        hints.push(path);
      }
    }
  }
  return [...new Set(hints)];
}

function extractPath(
  raw: Record<string, unknown> | null | undefined
): string | null {
  if (!raw) {
    return null;
  }
  const value = raw["path"];
  return typeof value === "string" && value ? value : null;
}

export default function WorkspaceShell({
  account,
  runtime,
  workspaces,
}: Props) {
  const [items, setItems] = useState<Workspace[]>(workspaces);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [connectRepoOpen, setConnectRepoOpen] = useState(false);

  const [projectName, setProjectName] = useState("");
  const [projectRoot, setProjectRoot] = useState("");
  const [repoName, setRepoName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [repoBranch, setRepoBranch] = useState("");

  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [filesPath, setFilesPath] = useState(".");
  const [filesError, setFilesError] = useState<string | null>(null);
  const [tab, setTab] = useState<ExecutionTab>("terminal");

  const [modelMode, setModelMode] = useState<ModelMode>("AUTO");
  const [currentModel, setCurrentModel] = useState<string | null>(
    runtime?.model ?? null
  );
  const [routing, setRouting] = useState<RunRouting | null>(null);
  const [routingTargets, setRoutingTargets] = useState<
    Record<string, ModelTargetPublic> | null
  >(null);
  const [pendingProposal, setPendingProposal] =
    useState<EscalationProposal | null>(null);
  const [escalationBusy, setEscalationBusy] = useState(false);
  const [chatReplies, setChatReplies] = useState<
    Array<{ role: "user" | "assistant"; text: string }>
  >([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  const activeWorkspace =
    items.find((item) => item.workspace_id === activeId) ?? null;

  const runtimeState = runtime?.state ?? null;
  const runtimeReady = runtimeState === "ready";
  const runActive =
    activeRun?.run.status === "queued" ||
    activeRun?.run.status === "running";

  const composerDisabledReason = (() => {
    if (!activeWorkspace) {
      // Workspace-less chat mode: no workspace tools, chat works.
      return null;
    }
    if (runActive) {
      return "An agent run is in progress for this workspace.";
    }
    if (runtimeState === "offline" || runtimeState === "failed") {
      return (
        "The model runtime is " +
        (runtimeState === "failed" ? "failed" : "offline") +
        " — start DEFENDcoder in Control Center, then retry."
      );
    }
    if (!runtimeReady) {
      return "The model runtime is starting — wait for READY, then retry.";
    }
    return null;
  })();

  useEffect(() => {
    if (!runActive || !activeWorkspace || !activeRun) {
      return;
    }
    const workspaceId = activeWorkspace.workspace_id;
    const runId = activeRun.run.run_id;

    const timer = window.setInterval(() => {
      void (async () => {
        try {
          const detail = await fetchRunDetail(
            fetch,
            "/v1",
            workspaceId,
            runId
          );
          setActiveRun(detail);
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 401) {
            window.clearInterval(timer);
            setError(
              "Session expired. Sign in again to continue."
            );
          }
        }
      })();
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runActive, activeWorkspace?.workspace_id, activeRun?.run.run_id]);

  async function refreshFiles(workspaceId: string, path: string) {
    try {
      const response = await listFiles(fetch, "/v1", workspaceId, path);
      setFiles(response.entries ?? []);
      setFilesPath(response.path);
      setFilesError(null);
    } catch (cause) {
      setFilesError(
        cause instanceof ApiError && cause.status === 404
          ? "The workspace root does not exist on this host yet."
          : "Unable to load workspace files."
      );
    }
  }

  async function refreshRoutingAndEscalations(
    workspaceId: string,
    runId: string
  ) {
    try {
      const data = await fetchRouting(fetch, "/v1", workspaceId, runId);
      setRouting(data.routing);
      setRoutingTargets(data.targets);
      if (data.routing) {
        setCurrentModel(data.routing.selected_model);
        setModelMode(
          (data.routing.requested_mode as ModelMode) || "AUTO"
        );
      }
    } catch {
      // transient; next poll retries
    }
    try {
      const proposals = await fetchEscalations(
        fetch,
        "/v1",
        workspaceId,
        runId
      );
      const pending = proposals.find((p) => p.status === "pending") ?? null;
      setPendingProposal(pending);
    } catch {
      // transient
    }
  }

  useEffect(() => {
    if (!activeRun || !activeWorkspace) {
      return;
    }
    const workspaceId = activeWorkspace.workspace_id;
    const runId = activeRun.run.run_id;

    void refreshRoutingAndEscalations(workspaceId, runId);
    const timer = window.setInterval(() => {
      void refreshRoutingAndEscalations(workspaceId, runId);
    }, 3000);

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRun?.run.run_id, activeWorkspace?.workspace_id]);

  async function chooseMode(mode: ModelMode) {
    if (!activeWorkspace || !activeRun) {
      setModelMode(mode);
      return;
    }
    try {
      const csrf = csrfToken();
      const routed = await selectModel(
        fetch,
        "/v1",
        activeWorkspace.workspace_id,
        activeRun.run.run_id,
        mode,
        csrf
      );
      setRouting(routed);
      setCurrentModel(routed.selected_model);
      setModelMode((routed.requested_mode as ModelMode) || "AUTO");
      setError(null);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to change model."
      );
    }
  }

  async function handleApproveEscalation() {
    if (!activeWorkspace || !activeRun || !pendingProposal) {
      return;
    }
    setEscalationBusy(true);
    try {
      const csrf = csrfToken();
      const routed = await approveEscalation(
        fetch,
        "/v1",
        activeWorkspace.workspace_id,
        activeRun.run.run_id,
        pendingProposal.proposal_id,
        csrf
      );
      setRouting(routed);
      setCurrentModel(routed.selected_model);
      setPendingProposal(null);
      setError(null);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Approval failed."
      );
    } finally {
      setEscalationBusy(false);
    }
  }

  async function handleStayOnCurrent() {
    if (!activeWorkspace || !activeRun || !pendingProposal) {
      return;
    }
    setEscalationBusy(true);
    try {
      const csrf = csrfToken();
      await denyEscalation(
        fetch,
        "/v1",
        activeWorkspace.workspace_id,
        activeRun.run.run_id,
        pendingProposal.proposal_id,
        csrf
      );
      setPendingProposal(null);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to stay on the current model."
      );
    } finally {
      setEscalationBusy(false);
    }
  }

  async function handleUseSolInstead() {
    await chooseMode("SOL");
    setPendingProposal(null);
  }

  async function handleCancelRun() {
    await handleStayOnCurrent();
    setError("Run cancelled by owner.");
  }

  async function sendChatMessage(message: string) {
    const value = message.trim();
    if (!value || chatBusy) {
      return;
    }
    setChatBusy(true);
    setError(null);
    try {
      const csrf = csrfToken();
      const result = await sendChat(fetch, "/v1", value, csrf);
      setChatReplies((current) => [
        ...current,
        { role: "user", text: value },
        { role: "assistant", text: result.reply },
      ]);
      setCurrentModel(result.model);
      setChatInput("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 503) {
        setError(
          "DeepSeek is not configured; workspace-less chat is unavailable."
        );
      } else {
        setError(
          cause instanceof ApiError ? cause.message : "Chat failed."
        );
      }
    } finally {
      setChatBusy(false);
    }
  }

  async function selectWorkspace(workspaceId: string) {
    setActiveId(workspaceId);
    setError(null);
    setActiveRun(null);
    setPrompt("");
    setFiles([]);
    setFilesPath(".");
    setFilesError(null);

    try {
      const runs = await listRuns(fetch, "/v1", workspaceId);
      if (runs.length > 0) {
        const latest = runs[0];
        const detail = await fetchRunDetail(
          fetch,
          "/v1",
          workspaceId,
          latest.run_id
        );
        setActiveRun(detail);
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("Session expired. Sign in again to continue.");
      }
    }

    void refreshFiles(workspaceId, ".");
  }

  async function sendPrompt(rawPrompt: string) {
    const value = rawPrompt.trim();
    if (!value || runActive) {
      return;
    }
    if (!activeWorkspace) {
      await sendChatMessage(value);
      return;
    }

    const csrf = csrfToken();
    setError(null);

    try {
      const run = await createRun(
        fetch,
        "/v1",
        activeWorkspace.workspace_id,
        value,
        csrf
      );
      setActiveRun({ run, messages: [] });
      setPrompt("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("Session expired. Sign in again to continue.");
      } else if (cause instanceof ApiError && cause.status === 409) {
        setError(
          "Another agent run is already active for this workspace."
        );
      } else if (cause instanceof ApiError && cause.status === 503) {
        setError(
          "Agent execution is not connected. Start the model runtime " +
            "in Control Center, then retry."
        );
      } else {
        setError("Unable to start the agent run. Please try again.");
      }
    }
  }

  function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendPrompt(prompt);
  }

  async function createWorkspace(
    payload: CreateWorkspacePayload
  ) {
    if (busy) {
      return;
    }

    setError(null);
    setBusy(true);

    try {
      const csrf = csrfToken();
      const response = await fetch("/v1/workspaces", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (response.status === 403) {
        setError(
          "Session expired. Sign in again to continue."
        );
        return;
      }

      if (!response.ok) {
        setError(
          "DEFENDcoder could not create the workspace."
        );
        return;
      }

      const body = (await response.json()) as {
        workspace: Workspace;
      };

      setItems((current) => [
        body.workspace,
        ...current.filter(
          (item) =>
            item.workspace_id !== body.workspace.workspace_id
        ),
      ]);
      setActiveId(body.workspace.workspace_id);
      setNewProjectOpen(false);
      setConnectRepoOpen(false);
      setProjectName("");
      setProjectRoot("");
      setRepoName("");
      setRepoUrl("");
      setRepoBranch("");
      void refreshFiles(body.workspace.workspace_id, ".");
    } catch {
      setError(
        "Unable to reach DEFENDcoder. Please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  function submitNewProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const name = projectName.trim();
    const root = projectRoot.trim();

    if (!name || !root) {
      setError("Project name and local root are required.");
      return;
    }

    void createWorkspace({
      name,
      workspace_root: root,
    });
  }

  function submitConnectRepo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const name = repoName.trim();
    const url = repoUrl.trim();

    if (!name || !url) {
      setError("Repo name and repository URL are required.");
      return;
    }

    void createWorkspace({
      name,
      workspace_root: ".",
      repository_url: url,
      default_branch: repoBranch.trim() || null,
    });
  }

  async function logout() {
    if (busy) {
      return;
    }

    setError(null);
    setBusy(true);

    try {
      const csrf = csrfToken();
      const response = await fetch("/v1/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: csrf ? { "X-CSRF-Token": csrf } : {},
      });

      if (!response.ok) {
        setError("Sign out failed. Please try again.");
        return;
      }

      try {
        sessionStorage.removeItem("defendcoder_csrf");
      } catch {
        // ignore
      }

      window.location.href = "/";
    } catch {
      setError("Unable to reach DEFENDcoder. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const userPrompt = promptForRun(activeRun?.run);
  const conversation = activeRun ? activeRun.messages : [];
  const changedFiles = changedFileHints(conversation);

  const terminalMessages = conversation.filter(
    (message) => message.role === "tool" && message.kind === "terminal"
  );
  const testMessages = conversation.filter(
    (message) => message.role === "tool" && message.kind === "tests"
  );
  const diffMessages = conversation.filter(
    (message) => message.role === "tool" && message.kind === "diff"
  );
  const logMessages = conversation.filter(
    (message) => message.role === "log" || message.kind === "log"
  );

  const agentStateNotice = (() => {
    if (runActive) {
      const phase = activeRun!.run.phase ?? null;
      const label = phaseLabel(phase);
      const elapsed = runElapsedSeconds(activeRun!.run, Date.now());
      return elapsed === null
        ? `${label}…`
        : `${label}… (${elapsed}s)`;
    }
    if (activeRun?.run.status === "failed") {
      const reason = activeRun.run.reason ?? null;
      const reasonText =
        reason && reason !== "unknown"
          ? ` (${reason.replaceAll("_", " ")})`
          : "";
      return (
        "Agent run failed" +
        reasonText +
        (activeRun.run.error ? `: ${activeRun.run.error}` : ".")
      );
    }
    if (activeRun?.run.status === "succeeded") {
      return "Agent run complete.";
    }
    if (!activeWorkspace) {
      return "Select or create a workspace to begin.";
    }
    if (runtimeState === "offline" || runtimeState === "failed") {
      return "The model runtime is " + runtimeState + " — start it in Control Center.";
    }
    if (!runtimeReady) {
      return "The model runtime is starting — wait for READY.";
    }
    return "Ready — describe a coding task for the agent.";
  })();

  return (
    <main className="workspace-shell">
      <header className="workspace-topbar">
        <div className="workspace-brand">
          <span className="brand-defend">DEFEND</span>
          <span className="brand-coder">coder</span>
        </div>

        <div className="runtime-strip" aria-label="Model status">
          <div className={runtimeStateClass(runtimeState)}>
            <span className="runtime-label">Runtime</span>
            <strong>{runtimeLabel(runtimeState)}</strong>
          </div>

          <div>
            <span className="runtime-label">Model</span>
            <strong>{display(runtime?.model)}</strong>
          </div>

          <div>
            <span className="runtime-label">Provider</span>
            <strong>{display(runtime?.provider)}</strong>
          </div>

          <div>
            <span className="runtime-label">Context</span>
            <strong>
              {runtime?.context_limit
                ? `${display(runtime.context_used)} / ${display(runtime.context_limit)}`
                : "—"}
            </strong>
          </div>
        </div>

        <ModelSelector
          mode={modelMode}
          currentModel={currentModel ?? runtime?.model ?? ""}
          routing={routing}
          targets={routingTargets}
          role={account.role}
          disabled={!activeRun || !activeWorkspace}
          onChange={(mode) => void chooseMode(mode)}
        />

        <div className="workspace-account">
          <span>{account.username}</span>
          <span className="role-chip">{account.role}</span>

          {account.role === "admin" ? (
            <a href="/admin" className="admin-link">
              Admin
            </a>
          ) : null}

          <button
            type="button"
            className="logout-link"
            onClick={() => void logout()}
            disabled={busy}
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="workspace-grid">
        <aside className="workspace-sidebar">
          <section>
            <h2>Projects</h2>
            <button
              type="button"
              onClick={() => {
                setConnectRepoOpen(false);
                setError(null);
                setNewProjectOpen((open) => !open);
              }}
            >
              New Project
            </button>

            {newProjectOpen ? (
              <form
                className="workspace-form"
                aria-label="New local project"
                onSubmit={submitNewProject}
              >
                <label className="sr-only" htmlFor="project-name">
                  Project name
                </label>
                <input
                  id="project-name"
                  type="text"
                  placeholder="Project name"
                  value={projectName}
                  onChange={(event) =>
                    setProjectName(event.target.value)
                  }
                />

                <label className="sr-only" htmlFor="project-root">
                  Local workspace root
                </label>
                <input
                  id="project-root"
                  type="text"
                  placeholder="Local root path"
                  value={projectRoot}
                  onChange={(event) =>
                    setProjectRoot(event.target.value)
                  }
                />

                <button type="submit" disabled={busy}>
                  Create
                </button>
              </form>
            ) : null}
          </section>

          <section>
            <h2>Git Repos</h2>
            <button
              type="button"
              onClick={() => {
                setNewProjectOpen(false);
                setError(null);
                setConnectRepoOpen((open) => !open);
              }}
            >
              Connect Repo
            </button>

            {connectRepoOpen ? (
              <form
                className="workspace-form"
                aria-label="Connect repository"
                onSubmit={submitConnectRepo}
              >
                <label className="sr-only" htmlFor="repo-name">
                  Workspace name
                </label>
                <input
                  id="repo-name"
                  type="text"
                  placeholder="Workspace name"
                  value={repoName}
                  onChange={(event) =>
                    setRepoName(event.target.value)
                  }
                />

                <label className="sr-only" htmlFor="repo-url">
                  Repository URL
                </label>
                <input
                  id="repo-url"
                  type="text"
                  placeholder="https://github.com/org/repo.git"
                  spellCheck={false}
                  value={repoUrl}
                  onChange={(event) =>
                    setRepoUrl(event.target.value)
                  }
                />

                <label className="sr-only" htmlFor="repo-branch">
                  Default branch
                </label>
                <input
                  id="repo-branch"
                  type="text"
                  placeholder="Default branch (optional)"
                  value={repoBranch}
                  onChange={(event) =>
                    setRepoBranch(event.target.value)
                  }
                />

                <button type="submit" disabled={busy}>
                  Create
                </button>
              </form>
            ) : null}
          </section>

          <section>
            <h2>Workspaces</h2>

            <div className="workspace-list">
              {items.length === 0 ? (
                <p className="muted">No workspaces yet.</p>
              ) : (
                items.map((workspace) => {
                  const isActive =
                    workspace.workspace_id === activeId;

                  return (
                    <article
                      key={workspace.workspace_id}
                      className={
                        isActive
                          ? "workspace-card workspace-card-active"
                          : "workspace-card"
                      }
                      role="button"
                      tabIndex={0}
                      aria-pressed={isActive}
                      onClick={() =>
                        selectWorkspace(workspace.workspace_id)
                      }
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" ||
                          event.key === " "
                        ) {
                          event.preventDefault();
                          selectWorkspace(workspace.workspace_id);
                        }
                      }}
                    >
                      <strong>{workspace.name}</strong>
                      <span>
                        {workspace.repository_url ??
                          "Local workspace"}
                      </span>
                      <small>
                        {workspace.default_branch ?? "—"}
                      </small>
                    </article>
                  );
                })
              )}
            </div>
          </section>

          {error ? (
            <div className="workspace-error" role="alert">
              {error}
            </div>
          ) : null}
        </aside>

        <section className="agent-pane">
          <div className="pane-header">
            <div>
              <span className="eyebrow">Agent</span>
              <h1>DEFENDcoder Workspace</h1>
            </div>

            <div className="agent-actions">
              <button
                type="button"
                disabled={
                  !activeWorkspace || runActive || !runtimeReady
                }
                title={
                  !activeWorkspace
                    ? "Select a workspace first."
                    : runActive
                      ? "An agent run is in progress."
                      : runtimeReady
                        ? "Run the workspace test suite via the agent."
                        : "The model runtime is not ready."
                }
                onClick={() => void sendPrompt(RUN_TESTS_PROMPT)}
              >
                Run Tests
              </button>
              <button
                type="button"
                disabled={
                  !activeWorkspace || runActive || !runtimeReady
                }
                title={
                  !activeWorkspace
                    ? "Select a workspace first."
                    : runActive
                      ? "An agent run is in progress."
                      : runtimeReady
                        ? "Review current changes via the agent."
                        : "The model runtime is not ready."
                }
                onClick={() => void sendPrompt(REVIEW_CHANGES_PROMPT)}
              >
                Review Changes
              </button>
            </div>
          </div>

          <div className="agent-conversation">
            {!activeWorkspace ? (
              chatReplies.length === 0 ? (
                <div className="empty-agent-state">
                  <strong>DEFENDcoder Chat</strong>
                  <p>
                    No workspace attached — advice and coding discussion are
                    available without filesystem or tool access.
                  </p>
                </div>
              ) : (
                chatReplies.map((message, index) => (
                  <article
                    key={index}
                    className={`agent-message agent-message-${
                      message.role === "user" ? "user" : "assistant"
                    }`}
                  >
                    <span className="message-role">
                      {message.role === "user" ? "You" : "Agent"}
                    </span>
                    <p className="message-content">{message.text}</p>
                  </article>
                ))
              )
            ) : !activeRun ? (
              <div className="empty-agent-state">
                <strong>{activeWorkspace.name}</strong>
                <p>{agentStateNotice}</p>
              </div>
            ) : (
              <>
                <div className="run-banner">
                  <span className="run-status-chip">
                    {runStatusLabel(activeRun.run.status)}
                  </span>
                  <span className="run-prompt-text">{userPrompt}</span>
                  {!runActive &&
                    ["failed", "partial_success", "cancelled"].includes(
                      activeRun.run.status
                    ) &&
                    runReasonLabel(activeRun.run.reason) && (
                      <span className="run-reason">
                        {runReasonLabel(activeRun.run.reason)}
                      </span>
                    )}
                </div>

                {conversation.length === 0 ? (
                  <div className="empty-agent-state">
                    <p>
                      {runActive
                        ? "The agent is working…"
                        : "This run has no output yet."}
                    </p>
                  </div>
                ) : (
                  conversation.map((message) => (
                    <article
                      key={message.seq}
                      className={`agent-message agent-message-${message.role}`}
                    >
                      {message.role === "assistant" ? (
                        <>
                          <span className="message-role">Agent</span>
                          {message.content ? (
                            <p className="message-content">
                              {message.content}
                            </p>
                          ) : null}
                          {message.tool_calls &&
                          message.tool_calls.length > 0 ? (
                            <div className="tool-call-list">
                              {message.tool_calls.map((call) => (
                                <span
                                  key={call.id}
                                  className="tool-call-chip"
                                >
                                  {call.name}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </>
                      ) : message.role === "tool" ? (
                        <div
                          className={`tool-result tool-result-${message.kind ?? "log"}`}
                        >
                          <span className="message-role">
                            {message.tool_name ?? "tool"}
                          </span>
                          <span
                            className={
                              message.ok === false
                                ? "tool-result-error"
                                : "tool-result-ok"
                            }
                          >
                            {message.ok === false ? "failed" : "ok"}
                          </span>
                          {message.tool_result ? (
                            <pre>{message.tool_result}</pre>
                          ) : null}
                        </div>
                      ) : (
                        <div className="agent-log-line">
                          <span className="message-role">Log</span>
                          <span>{message.content}</span>
                        </div>
                      )}
                    </article>
                  ))
                )}
              </>
            )}
          </div>

          <form className="agent-composer" onSubmit={submitPrompt}>
            <textarea
              aria-label="Coding task"
              placeholder={
                composerDisabledReason ??
                (activeWorkspace
                  ? "Describe a coding task for the agent…"
                  : "Ask DEFENDcoder anything — no workspace needed…")
              }
              disabled={composerDisabledReason !== null}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !event.shiftKey &&
                  !event.nativeEvent.isComposing
                ) {
                  event.preventDefault();
                  void sendPrompt(prompt);
                }
              }}
            />
            <button
              type="submit"
              disabled={composerDisabledReason !== null || !prompt.trim()}
            >
              Send
            </button>
          </form>
        </section>

        <aside className="review-pane">
          <div className="pane-header compact">
            <div>
              <span className="eyebrow">Workspace</span>
              <h2>Files</h2>
            </div>
            {activeWorkspace ? (
              <button
                type="button"
                className="refresh-files"
                onClick={() =>
                  void refreshFiles(
                    activeWorkspace.workspace_id,
                    filesPath
                  )
                }
                disabled={busy}
              >
                Refresh
              </button>
            ) : null}
          </div>

          <div className="changed-files">
            {!activeWorkspace ? (
              <p className="muted">
                Files of the active workspace will appear here.
              </p>
            ) : filesError ? (
              <p className="muted">{filesError}</p>
            ) : (
              <>
                <div className="files-breadcrumb">
                  {filesPath !== "." ? (
                    <button
                      type="button"
                      onClick={() =>
                        void refreshFiles(
                          activeWorkspace.workspace_id,
                          upOne(filesPath)
                        )
                      }
                    >
                      ↑ {upOne(filesPath)}
                    </button>
                  ) : (
                    <span>./</span>
                  )}
                </div>
                <ul className="file-tree">
                  {files.length === 0 ? (
                    <li className="muted">(empty directory)</li>
                  ) : (
                    files.map((entry) => (
                      <li key={entry.name}>
                        {entry.type === "directory" ? (
                          <button
                            type="button"
                            className="file-dir"
                            onClick={() =>
                              void refreshFiles(
                                activeWorkspace.workspace_id,
                                joinPath(filesPath, entry.name)
                              )
                            }
                          >
                            {entry.name}/
                          </button>
                        ) : (
                          <span className="file-entry">{entry.name}</span>
                        )}
                      </li>
                    ))
                  )}
                </ul>
              </>
            )}
          </div>
        </aside>

        <section className="execution-pane">
          <nav className="execution-tabs" aria-label="Execution output">
            <button
              type="button"
              className={tab === "terminal" ? "execution-tab-active" : ""}
              onClick={() => setTab("terminal")}
            >
              Terminal
            </button>
            <button
              type="button"
              className={tab === "tests" ? "execution-tab-active" : ""}
              onClick={() => setTab("tests")}
            >
              Tests
            </button>
            <button
              type="button"
              className={tab === "diff" ? "execution-tab-active" : ""}
              onClick={() => setTab("diff")}
            >
              Diff
            </button>
            <button
              type="button"
              className={tab === "logs" ? "execution-tab-active" : ""}
              onClick={() => setTab("logs")}
            >
              Logs
            </button>
          </nav>

          <div className="execution-output">
            <OutputPane
              tab={tab}
              terminalMessages={terminalMessages}
              testMessages={testMessages}
              diffMessages={diffMessages}
              logMessages={logMessages}
              run={activeRun?.run ?? null}
              changedFiles={changedFiles}
            />
          </div>
        </section>
      </div>

      {pendingProposal && activeRun && activeWorkspace ? (
        <EscalationModal
          proposal={pendingProposal}
          runtimeState={
            routingTargets?.["Qwen/Qwen3-Coder-Next"]?.available
              ? "READY"
              : "STOPPED_RETAINED"
          }
          busy={escalationBusy}
          onApprove={() => void handleApproveEscalation()}
          onStay={() => void handleStayOnCurrent()}
          onUseSol={() => void handleUseSolInstead()}
          onCancelRun={() => void handleCancelRun()}
        />
      ) : null}
    </main>
  );
}

function OutputPane({
  tab,
  terminalMessages,
  testMessages,
  diffMessages,
  logMessages,
  run,
  changedFiles,
}: {
  tab: ExecutionTab;
  terminalMessages: RunMessage[];
  testMessages: RunMessage[];
  diffMessages: RunMessage[];
  logMessages: RunMessage[];
  run: RunRecord | null;
  changedFiles: string[];
}) {
  if (tab === "terminal") {
    return <MessageList messages={terminalMessages} empty="No terminal output yet." />;
  }
  if (tab === "tests") {
    return <MessageList messages={testMessages} empty="No test output yet." />;
  }
  if (tab === "diff") {
    if (diffMessages.length > 0) {
      return <MessageList messages={diffMessages} empty="No diff output yet." />;
    }
    if (changedFiles.length > 0) {
      return (
        <pre>
          Changed files in the latest run:
          {"\n" + changedFiles.map((path) => `  ${path}`).join("\n")}
          {"\n\nRun “Review Changes” to see the full diff."}
        </pre>
      );
    }
    return <pre>No diff output yet. Use “Review Changes” to inspect changes.</pre>;
  }
  if (tab === "logs") {
    return (
      <MessageList
        messages={logMessages}
        empty={
          run
            ? `Run ${run.status}${run.error ? ` — ${run.error}` : ""}.`
            : "No run activity yet."
        }
      />
    );
  }
  return <pre>No output.</pre>;
}

function MessageList({
  messages,
  empty,
}: {
  messages: RunMessage[];
  empty: string;
}) {
  if (messages.length === 0) {
    return <pre>{empty}</pre>;
  }
  return (
    <div className="execution-messages">
      {messages.map((message) => (
        <pre
          key={message.seq}
          className={message.ok === false ? "execution-pre-error" : ""}
        >
          {message.tool_result ?? message.content ?? ""}
        </pre>
      ))}
    </div>
  );
}

function upOne(path: string): string {
  if (path === "." || path === "") {
    return ".";
  }
  const parts = path.split("/").filter(Boolean);
  parts.pop();
  return parts.length === 0 ? "." : parts.join("/");
}

function joinPath(base: string, name: string): string {
  if (base === "." || base === "") {
    return name;
  }
  return `${base}/${name}`;
}