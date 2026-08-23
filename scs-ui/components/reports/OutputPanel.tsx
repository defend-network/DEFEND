"use client";

import { useState } from "react";
import type { ComposeResult, JobRecord, ValidationCheck } from "@/lib/reportTypes";
import { composeReport, downloadUrl, listOutputs } from "@/lib/reportsApi";
import { validationGroup, type ValidationGroup } from "@/lib/reportStatus";

const GROUP_ORDER: ValidationGroup[] = [
  "MISSING REQUIRED",
  "DATA CONFLICT",
  "FORMULA",
  "EVIDENCE",
  "LAYOUT",
  "OTHER",
];

export function OutputPanel({
  record,
  jobId,
  outputs,
  setOutputs,
  lastValidation,
  setLastValidation,
  onBack,
}: {
  record: JobRecord;
  jobId: string;
  outputs: string[];
  setOutputs: (outputs: string[]) => void;
  lastValidation: ComposeResult | null;
  setLastValidation: (result: ComposeResult) => void;
  onBack: () => void;
}) {
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function compose() {
    setError(null);
    setComposing(true);
    try {
      const result = await composeReport(jobId);
      setLastValidation(result);
      const fresh = await listOutputs(jobId);
      setOutputs(fresh.outputs);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Compose failed");
    } finally {
      setComposing(false);
    }
  }

  async function openOutput(filename: string) {
    try {
      const url = await downloadUrl(jobId, filename);
      window.open(url, "_blank");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not open workbook");
    }
  }

  const grouped = lastValidation
    ? GROUP_ORDER.map((group) => ({
        group,
        checks: lastValidation.checks.filter((check) => validationGroup(check) === group),
      })).filter((entry) => entry.checks.length > 0)
    : [];
  const summary = lastValidation
    ? {
        pass: lastValidation.checks.filter((c) => c.status === "PASS").length,
        warn: lastValidation.checks.filter((c) => c.status === "WARN").length,
        block: lastValidation.checks.filter((c) => c.status === "BLOCK").length,
      }
    : null;

  return (
    <section className="reports-panel">
      <h4>Compose & export</h4>
      <p className="muted">
        Generates the workbook from the structured record, then runs the validation gate. A BLOCK
        means the file is not releasable until fixed.
      </p>
      {error && (
        <p role="alert" className="login-error">
          {error}
        </p>
      )}
      <div className="reports-actions">
        <button className="button-primary" onClick={compose} disabled={composing}>
          {composing ? "Composing…" : "Compose report"}
        </button>
      </div>
      {summary && (
        <div className="reports-validation-summary">
          <span className={`pill ${summary.block > 0 ? "status-bad" : summary.warn > 0 ? "status-warn" : "status-ok"}`}>
            {summary.block > 0 ? "BLOCKED" : summary.warn > 0 ? "WARNINGS" : "PASS"}
          </span>
          <span>
            {summary.pass} pass · {summary.warn} warn · {summary.block} block
          </span>
        </div>
      )}
      {grouped.map(({ group, checks }) => (
        <div key={group} className="reports-validation-group">
          <h6 className="reports-group-label">{group}</h6>
          <ul>
            {checks.map((check, index) => (
              <li key={`${check.name}-${index}`} className={`reports-validation-${check.status.toLowerCase()}`}>
                <span className="pill">{check.status}</span>
                <span>{check.message}</span>
                {check.status === "BLOCK" && <ActionsForCheck check={check} />}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <h5>Outputs</h5>
      {outputs.length === 0 && <div className="empty">No workbook generated yet.</div>}
      <ul className="reports-plan-list">
        {[...outputs].reverse().map((filename) => (
          <li key={filename}>
            <div>
              <strong>{filename}</strong>
              <p className="muted">version {versionLabel(filename)}</p>
            </div>
            <button className="button-secondary" onClick={() => void openOutput(filename)}>
              Open / download
            </button>
          </li>
        ))}
      </ul>
      <div className="reports-actions">
        <button className="button-secondary" onClick={onBack}>
          ← Review
        </button>
      </div>
    </section>
  );
}

function versionLabel(filename: string): string {
  const match = filename.match(/_v(\d+)\.xlsx$/);
  if (match) {
    return `v${match[1]}`;
  }
  return "v01";
}

function ActionsForCheck({ check }: { check: ValidationCheck }) {
  const message = check.message;
  const hints: { label: string; hint: string }[] = [];
  const idMatch = message.match(/^(\S+)/);
  if (idMatch) {
    const id = idMatch[1];
    hints.push({
      label: `Enter ${id} data`,
      hint: "Go to EQUIPMENT or READINGS and add the missing value.",
    });
  }
  if (message.toLowerCase().includes("design")) {
    hints.push({
      label: "Mark design not provided",
      hint: "Add a note like “design not provided” on the device.",
    });
  }
  return (
    <div className="reports-fix-hints">
      {hints.length === 0 ? (
        <span className="muted">Fix in the EQUIPMENT, READINGS or PLAN step.</span>
      ) : (
        hints.map((hint) => (
          <span key={hint.label} title={hint.hint}>
            → {hint.label}
          </span>
        ))
      )}
    </div>
  );
}