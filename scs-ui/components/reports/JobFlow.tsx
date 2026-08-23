"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getJob, replaceJob } from "@/lib/reportsApi";
import type { ComposeResult, JobRecord } from "@/lib/reportTypes";
import { deriveStatus, statusLabel, statusTone } from "@/lib/reportStatus";
import { JobDataForm } from "./JobDataForm";
import { EquipmentForm } from "./EquipmentForm";
import { ReadingsPanels } from "./ReadingsPanels";
import { PhotosForm } from "./PhotosForm";
import { ReviewPanel } from "./ReviewPanel";
import { PlanPanel } from "./PlanPanel";
import { OutputPanel } from "./OutputPanel";

const STEPS = ["JOB", "EQUIPMENT", "READINGS", "PHOTOS", "REVIEW", "REPORT"] as const;
type Step = (typeof STEPS)[number];

export type SaveState = "saved" | "saving" | "error";

export function JobFlow({
  jobId,
  onBack,
}: {
  jobId: string;
  onBack: () => void;
}) {
  const [record, setRecord] = useState<JobRecord | null>(null);
  const [step, setStep] = useState<Step>("JOB");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [planSections, setPlanSections] = useState<string[] | null>(null);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [lastValidation, setLastValidation] = useState<ComposeResult | null>(null);
  const pendingRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestRef = useRef<JobRecord | null>(null);

  useEffect(() => {
    getJob(jobId)
      .then((loaded) => {
        latestRef.current = loaded;
        setRecord(loaded);
      })
      .catch((cause) =>
        setLoadError(cause instanceof Error ? cause.message : "Could not load job"),
      );
  }, [jobId]);

  const commit = useCallback(
    (updated: JobRecord) => {
      latestRef.current = updated;
      setRecord(updated);
      setSaveState("saving");
      if (pendingRef.current) {
        clearTimeout(pendingRef.current);
      }
      pendingRef.current = setTimeout(() => {
        replaceJob(jobId, updated)
          .then(() => setSaveState("saved"))
          .catch(() => setSaveState("error"));
      }, 500);
    },
    [jobId],
  );

  useEffect(
    () => () => {
      if (pendingRef.current) {
        clearTimeout(pendingRef.current);
      }
    },
    [],
  );

  if (loadError) {
    return (
      <div className="reports-flow">
        <p role="alert" className="login-error">
          {loadError}
        </p>
        <button className="button-secondary" onClick={onBack}>
          Back to reports
        </button>
      </div>
    );
  }

  if (!record) {
    return <p className="chat-placeholder">Loading job…</p>;
  }

  const status = deriveStatus(record, planSections, lastValidation, outputs);
  const statusLabelText = statusLabel(status);

  return (
    <div className="reports-flow">
      <div className="reports-flow-header">
        <div>
          <button className="button-link" onClick={onBack}>
            ← Reports
          </button>
          <h3>
            {record.metadata.project_name || "Untitled job"}{" "}
            {record.metadata.project_number ? `(${record.metadata.project_number})` : ""}
          </h3>
        </div>
        <div className="reports-flow-meta">
          <span className={`pill ${statusTone(status)}`}>{statusLabelText}</span>
          <span className="pill save-indicator">
            {saveState === "saving" ? "Saving…" : saveState === "error" ? "Save failed" : "Saved"}
          </span>
        </div>
      </div>
      <nav className="reports-steps" aria-label="Report workflow">
        {STEPS.map((name) => (
          <button
            key={name}
            className={name === step ? "reports-step active" : "reports-step"}
            onClick={() => setStep(name)}
          >
            {name}
          </button>
        ))}
      </nav>
      <div className="reports-step-body">
        {step === "JOB" && (
          <JobDataForm record={record} commit={commit} onNext={() => setStep("EQUIPMENT")} />
        )}
        {step === "EQUIPMENT" && (
          <EquipmentForm
            record={record}
            commit={commit}
            onNext={() => setStep("READINGS")}
            onBack={() => setStep("JOB")}
          />
        )}
        {step === "READINGS" && (
          <ReadingsPanels
            record={record}
            commit={commit}
            onNext={() => setStep("PHOTOS")}
            onBack={() => setStep("EQUIPMENT")}
          />
        )}
        {step === "PHOTOS" && (
          <PhotosForm
            record={record}
            commit={commit}
            onNext={() => setStep("REVIEW")}
            onBack={() => setStep("READINGS")}
          />
        )}
        {step === "REVIEW" && (
          <ReviewPanel
            record={record}
            commit={commit}
            onNext={() => setStep("REPORT")}
            onBack={() => setStep("PHOTOS")}
          />
        )}
        {step === "REPORT" && (
          <div className="reports-report-grid">
            <PlanPanel
              record={record}
              commit={commit}
              planSections={planSections}
              setPlanSections={setPlanSections}
            />
            <OutputPanel
              record={record}
              jobId={jobId}
              outputs={outputs}
              setOutputs={setOutputs}
              lastValidation={lastValidation}
              setLastValidation={setLastValidation}
              onBack={() => setStep("REVIEW")}
            />
          </div>
        )}
      </div>
    </div>
  );
}