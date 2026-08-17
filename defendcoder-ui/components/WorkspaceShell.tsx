"use client";

type Account = {
  username: string;
  role: "admin" | "consumer";
};

type RuntimeStatus = {
  state?: string | null;
  model?: string | null;
  provider?: string | null;
  context_used?: number | null;
  context_limit?: number | null;
};

type Workspace = {
  workspace_id: string;
  name: string;
  repository_url?: string | null;
  default_branch?: string | null;
};

type Props = {
  account: Account;
  runtime: RuntimeStatus | null;
  workspaces: Workspace[];
};

function display(value: string | number | null | undefined) {
  return value === null || value === undefined || value === ""
    ? "?"
    : String(value);
}

export default function WorkspaceShell({
  account,
  runtime,
  workspaces,
}: Props) {
  const runtimeAvailable =
    runtime !== null &&
    runtime.state !== null &&
    runtime.state !== undefined;

  return (
    <main className="workspace-shell">
      <header className="workspace-topbar">
        <div className="workspace-brand">
          <span className="brand-defend">DEFEND</span>
          <span className="brand-coder">coder</span>
        </div>

        <div className="runtime-strip" aria-label="Model status">
          <div>
            <span className="runtime-label">Runtime</span>
            <strong>
              {runtimeAvailable ? display(runtime?.state) : "Unavailable"}
            </strong>
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
              {display(runtime?.context_used)}
              {" / "}
              {display(runtime?.context_limit)}
            </strong>
          </div>
        </div>

        <div className="workspace-account">
          <span>{account.username}</span>
          <span className="role-chip">{account.role}</span>

          {account.role === "admin" ? (
            <a href="/admin" className="admin-link">
              Admin
            </a>
          ) : null}
        </div>
      </header>

      <div className="workspace-grid">
        <aside className="workspace-sidebar">
          <section>
            <h2>Projects</h2>
            <button type="button">New Project</button>
          </section>

          <section>
            <h2>Git Repos</h2>
            <button type="button">Connect Repo</button>
          </section>

          <section>
            <h2>Workspaces</h2>

            <div className="workspace-list">
              {workspaces.length === 0 ? (
                <p className="muted">No workspaces yet.</p>
              ) : (
                workspaces.map((workspace) => (
                  <article
                    key={workspace.workspace_id}
                    className="workspace-card"
                  >
                    <strong>{workspace.name}</strong>
                    <span>
                      {workspace.repository_url ?? "Local workspace"}
                    </span>
                    <small>
                      {workspace.default_branch ?? "?"}
                    </small>
                  </article>
                ))
              )}
            </div>
          </section>
        </aside>

        <section className="agent-pane">
          <div className="pane-header">
            <div>
              <span className="eyebrow">Agent</span>
              <h1>DEFENDcoder Workspace</h1>
            </div>

            <div className="agent-actions">
              <button type="button">Run Tests</button>
              <button type="button">Review Changes</button>
            </div>
          </div>

          <div className="agent-conversation">
            <div className="empty-agent-state">
              <strong>Ready for a coding task.</strong>
              <p>
                Select or create a workspace, then describe what you want
                built, fixed, reviewed, or tested.
              </p>
            </div>
          </div>

          <form className="agent-composer">
            <textarea
              aria-label="Coding task"
              placeholder="Ask DEFENDcoder to inspect, implement, debug, test, or review..."
            />
            <button type="submit">Send</button>
          </form>
        </section>

        <aside className="review-pane">
          <div className="pane-header compact">
            <div>
              <span className="eyebrow">Changes</span>
              <h2>Review</h2>
            </div>
          </div>

          <div className="changed-files">
            <p className="muted">
              Changed files will appear here when an agent run modifies the
              active workspace.
            </p>
          </div>
        </aside>

        <section className="execution-pane">
          <nav className="execution-tabs" aria-label="Execution output">
            <button type="button">Terminal</button>
            <button type="button">Tests</button>
            <button type="button">Diff</button>
            <button type="button">Logs</button>
          </nav>

          <div className="execution-output">
            <pre>Workspace output will appear here.</pre>
          </div>
        </section>
      </div>
    </main>
  );
}
