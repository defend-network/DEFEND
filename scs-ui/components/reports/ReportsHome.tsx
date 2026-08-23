"use client";

import { useCallback, useEffect, useState } from "react";
import { listJobs, listOutputs, getJob, type JobSummary } from "@/lib/reportsApi";
import type { JobRecord } from "@/lib/reportTypes";
import { ApiError } from "@/lib/api";
import { deriveStatus, statusLabel, statusTone, type ReportStatus } from "@/lib/reportStatus";
import { NewJobForm } from "./NewJobForm";

type Row = {
  summary: JobSummary;
  record: JobRecord | null;
  status: ReportStatus;
  outputs: string[];
};

type Phase = "loading" | "loaded" | "error";

const QUICK_START = [
  "Open the Control Center",
  "Launch SCS",
  "Open Reports",
  "New TAB Job",
  "Select or add the hiring contractor",
  "Enter job/site info",
  "Add equipment and readings",
  "Upload photos",
  "Review missing or uncertain evidence",
  "Generate the report plan",
  "Compose the workbook",
  "Clear WARN / BLOCK items",
  "Export the XLSX",
];

export function ReportsHome({
  defaultTechnician,
  onOpen,
}: {
  defaultTechnician: string;
  onOpen: (jobId: string) => void;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authExpired, setAuthExpired] = useState(false);

  const refresh = useCallback(async () => {
    setPhase("loading");
    setError(null);
    setAuthExpired(false);
    try {
      const payload = await listJobs();
      const loaded = await Promise.all(
        payload.jobs.map(async (summary) => {
          let record: JobRecord | null = null;
          let outputs: string[] = [];
          try {
            record = await getJob(summary.job_id);
            outputs = (await listOutputs(summary.job_id)).outputs;
          } catch {
            // show the row with what we have
          }
          return {
            summary,
            record,
            outputs,
            status: record
              ? deriveStatus(record, null, null, outputs)
              : ("EVIDENCE_INCOMPLETE" as ReportStatus),
          };
        }),
      );
      setRows(loaded);
      setPhase("loaded");
    } catch (cause) {
      if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
        setAuthExpired(true);
      }
      setError(cause instanceof Error ? cause.message : "Could not load reports");
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (phase === "loading") {
    return <p className="chat-placeholder">Loading reports…</p>;
  }

  if (phase === "error") {
    return (
      <div className="reports-home" role="alert">
        <h3>Field reports</h3>
        {authExpired ? (
          <p className="login-error">
            Your session has expired. Sign in again, then retry.
          </p>
        ) : (
          <p className="login-error">{error}</p>
        )}
        <button className="button-primary" onClick={() => void refresh()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="reports-home">
      <details className="reports-quickstart">
        <summary>Quick start — field workflow</summary>
        <ol>
          {QUICK_START.map((step, index) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </details>
      <div className="reports-toolbar">
        <h3>Field reports</h3>
        <button
          className="button-primary"
          onClick={() => {
            setError(null);
            setCreating((current) => !current);
          }}
        >
          {creating ? "Close new job" : "+ New report"}
        </button>
      </div>
      {error && (
        <p role="alert" className="login-error">
          {error}
        </p>
      )}
      {creating && (
        <NewJobForm
          defaultTechnician={defaultTechnician}
          onCancel={() => setCreating(false)}
          onCreated={(record) => {
            setCreating(false);
            onOpen(record.metadata.job_id);
          }}
        />
      )}
      <div className="reports-list">
        {rows === null || rows.length === 0 ? (
          <div className="empty">
            No field reports yet. Start one with “New report”.
          </div>
        ) : (
          rows.map((row) => (
            <article className="job-card reports-row" key={row.summary.job_id}>
              <div className="reports-row-main">
                <span className={`pill ${statusTone(row.status)}`}>{statusLabel(row.status)}</span>
                <h4>{row.summary.project_name}</h4>
                <p>
                  {row.summary.project_number ?? "—"} · {row.summary.test_date ?? "no date"} ·{" "}
                  {row.summary.technician}
                </p>
                <p className="muted">
                  {row.summary.hiring_contractor ?? "no contractor"} · updated{" "}
                  {row.summary.updated_at.replace("T", " ").slice(0, 16)}
                </p>
              </div>
              <div className="reports-row-actions">
                {row.outputs.length > 0 && (
                  <span className="pill">{row.outputs.length} export{row.outputs.length > 1 ? "s" : ""}</span>
                )}
                <button className="button-secondary" onClick={() => onOpen(row.summary.job_id)}>
                  Open
                </button>
              </div>
            </article>
          ))
        )}
      </div>
    </div>
  );
}