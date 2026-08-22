"use client";

import { EscalationProposal } from "@/app/workspace/load-workspace";

type Props = {
  proposal: EscalationProposal;
  runtimeState: string | null;
  busy: boolean;
  onApprove: () => void;
  onStay: () => void;
  onUseSol: () => void;
  onCancelRun: () => void;
};

export default function EscalationModal({
  proposal,
  runtimeState,
  busy,
  onApprove,
  onStay,
  onUseSol,
  onCancelRun,
}: Props) {
  const isNext = proposal.to_model === "Qwen/Qwen3-Coder-Next";
  const isSol = proposal.to_model === "gpt-5.6-sol";
  const title = isNext
    ? "DEFENDcoder recommends stronger intelligence"
    : "Frontier escalation requested";

  return (
    <div className="escalation-modal-backdrop" role="dialog" aria-modal="true">
      <div className="escalation-modal">
        <span className="eyebrow">Escalation</span>
        <h2>{title}</h2>

        <dl className="escalation-facts">
          <div>
            <dt>Current</dt>
            <dd>{proposal.from_model}</dd>
          </div>
          <div>
            <dt>Recommended</dt>
            <dd>{proposal.to_model}</dd>
          </div>
          <div>
            <dt>Reason</dt>
            <dd>{proposal.human_summary}</dd>
          </div>
          {proposal.evidence.length > 0 ? (
            <div>
              <dt>Evidence</dt>
              <dd>
                <ul>
                  {proposal.evidence.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Attempts</dt>
            <dd>{proposal.attempt_count}</dd>
          </div>
          <div>
            <dt>Failed tests</dt>
            <dd>{proposal.tests_failed}</dd>
          </div>
          <div>
            <dt>Runtime</dt>
            <dd>{runtimeState ?? "unknown"}</dd>
          </div>
          <div>
            <dt>GPU action</dt>
            <dd>
              {proposal.requires_gpu_resume
                ? "Resume/start required"
                : "No GPU"}
            </dd>
          </div>
          <div>
            <dt>Estimated cost</dt>
            <dd>
              {proposal.estimated_incremental_cost ??
                "price confirmation required"}
            </dd>
          </div>
        </dl>

        <div className="escalation-actions">
          <button
            type="button"
            className="escalation-approve"
            disabled={busy}
            onClick={onApprove}
          >
            {isSol ? "Approve Sol" : "Approve Next"}
          </button>
          <button type="button" disabled={busy} onClick={onStay}>
            {isSol ? "Stay on Next" : "Stay on DeepSeek"}
          </button>
          {!isSol ? (
            <button type="button" disabled={busy} onClick={onUseSol}>
              Use Sol Instead
            </button>
          ) : null}
          <button type="button" disabled={busy} onClick={onCancelRun}>
            Cancel Run
          </button>
        </div>
      </div>
    </div>
  );
}
