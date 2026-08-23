"use client";

import { useEffect, useState } from "react";

import {
  ApiError,
  AttemptRecord,
  CheckpointRecord,
  fetchRunAttempts,
  fetchRunCheckpoints,
  fetchRunTelemetry,
  fetchRunToolExecutions,
  ModelCall,
  resolveRecovery,
  ToolExecution,
} from "@/app/workspace/load-workspace";

type Section = "attempts" | "checkpoints" | "tools" | "telemetry";

export default function RunInspector({
  workspaceId,
  runId,
  onResolved,
}: {
  workspaceId: string;
  runId: string;
  onResolved?: () => void;
}) {
  const [attempts, setAttempts] = useState<AttemptRecord[]>([]);
  const [checkpoints, setCheckpoints] = useState<CheckpointRecord[]>([]);
  const [tools, setTools] = useState<ToolExecution[]>([]);
  const [telemetry, setTelemetry] = useState<ModelCall[]>([]);
  const [section, setSection] = useState<Section>("attempts");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const [a, c, t, m] = await Promise.all([
        fetchRunAttempts(fetch, "/v1", workspaceId, runId),
        fetchRunCheckpoints(fetch, "/v1", workspaceId, runId),
        fetchRunToolExecutions(fetch, "/v1", workspaceId, runId),
        fetchRunTelemetry(fetch, "/v1", workspaceId, runId),
      ]);
      setAttempts(a);
      setCheckpoints(c);
      setTools(t);
      setTelemetry(m);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unable to load run detail.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, runId]);

  async function resolve(executionId: string, resolution: "CONFIRMED_APPLIED" | "CONFIRMED_NOT_APPLIED" | "ABANDON_RUN") {
    setBusy(true);
    setError(null);
    const csrf = window.sessionStorage.getItem("defendcoder_csrf");
    try {
      await resolveRecovery(fetch, "/v1", workspaceId, runId, executionId, resolution, csrf);
      await load();
      onResolved?.();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Resolution failed.");
    } finally {
      setBusy(false);
    }
  }

  const unknownTools = tools.filter((t) => t.state === "UNKNOWN_AFTER_INTERRUPTION");

  return (
    <div className="run-inspector">
      {error && <p className="muted">{error}</p>}
      <nav className="inspector-tabs" aria-label="Run detail">
        {(["attempts", "checkpoints", "tools", "telemetry"] as Section[]).map((s) => (
          <button
            key={s}
            type="button"
            className={section === s ? "inspector-tab-active" : ""}
            onClick={() => setSection(s)}
          >
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </nav>

      {section === "attempts" && (
        <ul className="inspector-list">
          {attempts.length === 0 && <li className="muted">No attempts recorded.</li>}
          {attempts.map((a) => (
            <li key={a.attempt_id} className="inspector-item">
              <span className="inspector-key">{a.attempt_id.slice(0, 8)}…</span>
              <span>checkpoint {a.checkpoint_revision ?? "—"}</span>
              <span>{a.state}</span>
              {a.failure_class && <span className="muted">{a.failure_class}</span>}
              <span className="muted">{a.summary}</span>
            </li>
          ))}
        </ul>
      )}

      {section === "checkpoints" && (
        <ul className="inspector-list">
          {checkpoints.length === 0 && <li className="muted">No checkpoints recorded.</li>}
          {checkpoints.map((c) => (
            <li key={c.checkpoint_id} className="inspector-item">
              <span className="inspector-key">rev {c.revision}</span>
              <span>{c.objective}</span>
              {c.completed_work.length > 0 && (
                <span className="muted">completed: {c.completed_work.join("; ")}</span>
              )}
              {c.current_failure && <span className="muted">failure: {c.current_failure}</span>}
            </li>
          ))}
        </ul>
      )}

      {section === "tools" && (
        <div>
          {unknownTools.length > 0 && (
            <div className="recovery-card" role="alert">
              <h3 className="recovery-title">RECOVERY REQUIRED</h3>
              <p className="recovery-note">
                This action may already have occurred. DEFENDcoder will not
                automatically repeat it. Choose an explicit outcome:
              </p>
              {unknownTools.map((t) => (
                <div key={t.execution_id} className="recovery-actions">
                  <span className="recovery-tool">{t.tool_name}</span>
                  <span className="recovery-exec">{t.execution_id.slice(0, 8)}…</span>
                  <button type="button" disabled={busy} onClick={() => void resolve(t.execution_id, "CONFIRMED_APPLIED")}>
                    Confirmed Applied
                  </button>
                  <button type="button" disabled={busy} onClick={() => void resolve(t.execution_id, "CONFIRMED_NOT_APPLIED")}>
                    Confirmed Not Applied
                  </button>
                  <button type="button" disabled={busy} onClick={() => void resolve(t.execution_id, "ABANDON_RUN")}>
                    Abandon Run
                  </button>
                </div>
              ))}
            </div>
          )}
          <ul className="inspector-list">
            {tools.length === 0 && <li className="muted">No tool executions recorded.</li>}
            {tools.map((t) => (
              <li key={t.execution_id} className="inspector-item">
                <span className="inspector-key">{t.tool_call_id}</span>
                <span>{t.tool_name}</span>
                <span>{t.mutation_class}</span>
                <span className={t.state === "UNKNOWN_AFTER_INTERRUPTION" ? "recovery-tool" : ""}>
                  {t.state}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {section === "telemetry" && (
        <div>
          <p className="muted">Cost: COST NOT AVAILABLE</p>
          <ul className="inspector-list">
            {telemetry.length === 0 && <li className="muted">No model calls recorded.</li>}
            {telemetry.map((m) => (
              <li key={m.step} className="inspector-item">
                <span className="inspector-key">step {m.step}</span>
                <span>{m.phase}</span>
                <span>in {m.input_tokens ?? "?"}</span>
                <span>out {m.output_tokens ?? "?"}</span>
                {m.finish_reason && <span className="muted">{m.finish_reason}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
