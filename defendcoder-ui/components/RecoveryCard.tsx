"use client";

import type { ToolExecution } from "@/app/workspace/load-workspace";

export default function RecoveryCard({
  executions,
}: {
  executions?: ToolExecution[];
}) {
  const unknown = (executions ?? []).filter(
    (e) => e.state === "UNKNOWN_AFTER_INTERRUPTION"
  );

  if (unknown.length === 0) {
    return null;
  }

  return (
    <div className="recovery-card" role="alert">
      <h3 className="recovery-title">RECOVERY REQUIRED</h3>
      <p className="recovery-note">
        This action may already have occurred. DEFENDcoder will not
        automatically repeat it.
      </p>
      <ul className="recovery-list">
        {unknown.map((e) => (
          <li key={e.execution_id}>
            <span className="recovery-tool">{e.tool_name}</span>
            <span className="recovery-exec">
              {e.execution_id.slice(0, 8)}…
            </span>
            <span className="recovery-args">
              mutation class: {e.mutation_class}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
