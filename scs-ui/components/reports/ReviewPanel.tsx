"use client";

import { useEffect, useState } from "react";
import type { Equipment, JobRecord, Measurement } from "@/lib/reportTypes";
import { visionStatus } from "@/lib/reportsApi";

export function ReviewPanel({
  record,
  commit,
  onNext,
  onBack,
}: {
  record: JobRecord;
  commit: (record: JobRecord) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [vision, setVision] = useState<{ status: string; provider: string | null; note: string } | null>(null);

  useEffect(() => {
    visionStatus()
      .then(setVision)
      .catch(() => setVision(null));
  }, []);

  function updateMeasurement(equipment: Equipment, index: number, next: Measurement) {
    const measurements = equipment.measurements.map((m, item) => (item === index ? next : m));
    commit({
      ...record,
      equipment: record.equipment.map((e) => (e.equipment_id === equipment.equipment_id ? { ...e, measurements } : e)),
    });
  }

  function confirmMeasurement(equipment: Equipment, index: number) {
    const measurement = equipment.measurements[index];
    updateMeasurement(equipment, index, { ...measurement, technician_confirmed: true });
  }

  function markNotApplicable(equipment: Equipment, index: number) {
    const measurement = equipment.measurements[index];
    updateMeasurement(equipment, index, { ...measurement, not_applicable: !measurement.not_applicable, value: null });
  }

  function removeMeasurement(equipment: Equipment, index: number) {
    commit({
      ...record,
      equipment: record.equipment.map((e) =>
        e.equipment_id === equipment.equipment_id
          ? { ...e, measurements: e.measurements.filter((_, item) => item !== index) }
          : e,
      ),
    });
  }

  const unconfirmed = record.equipment.flatMap((equipment) =>
    equipment.measurements
      .filter((m) => !m.technician_confirmed && !m.not_applicable)
      .map((m) => ({ equipment: equipment.equipment_id, field: m.field, measurement: m })),
  );

  return (
    <div>
      <h4>Evidence review</h4>
      <p className="muted">
        Every reading that reaches the report is listed here. Unconfirmed extracted values are never
        promoted silently — confirm, edit, or mark them not applicable.
      </p>
      {vision && vision.status === "NOT_CONFIGURED" && (
        <p className="reports-vision-note">
          Vision provider: <strong>NOT_CONFIGURED</strong> — all evidence below is
          technician-entered. Photo-extracted candidates (PHOTO_EXTRACTED / NEEDS_CONFIRMATION) will
          appear here once a provider is configured.
        </p>
      )}
      {unconfirmed.length > 0 && (
        <div className="reports-warning-block">
          <strong>{unconfirmed.length} reading{unconfirmed.length === 1 ? "" : "s"} need confirmation</strong>
          <ul>
            {unconfirmed.map((item) => (
              <li key={`${item.equipment}-${item.field}`}>
                {item.equipment} {item.field} ({String(item.measurement.value)} {item.measurement.unit}) —{" "}
                {item.measurement.source_type}
              </li>
            ))}
          </ul>
        </div>
      )}
      {record.equipment.map((equipment) => (
        <section className="reports-panel" key={equipment.equipment_id}>
          <h5>
            <span className="pill">{equipment.equipment_type}</span> {equipment.equipment_id}
          </h5>
          {equipment.measurements.length === 0 && <p className="muted">No readings recorded.</p>}
          <ul className="reports-evidence-list">
            {equipment.measurements.map((measurement, index) => (
              <li className="reports-evidence-card" key={`${measurement.field}-${index}`}>
                <div className="reports-evidence-value">
                  <span className="pill pill-field">{measurement.field}</span>
                  {measurement.not_applicable ? (
                    <span className="pill">N/A</span>
                  ) : (
                    <strong>
                      {String(measurement.value)} {measurement.unit}
                    </strong>
                  )}
                </div>
                <div className="reports-evidence-meta">
                  <span className={`pill ${measurement.source_type.startsWith("AI_") ? "pill-warn" : ""}`}>
                    {measurement.source_type.replace(/_/g, " ")}
                  </span>
                  {measurement.source_type.startsWith("AI_") && (
                    <span className={measurement.technician_confirmed ? "" : "pill pill-warn"}>
                      {measurement.technician_confirmed ? "confirmed" : "needs confirmation"}
                    </span>
                  )}
                  {measurement.confidence !== null && measurement.confidence !== undefined && (
                    <span className="pill">confidence {Math.round(measurement.confidence * 100)}%</span>
                  )}
                </div>
                <div className="reports-evidence-actions">
                  {measurement.source_type.startsWith("AI_") && !measurement.technician_confirmed && (
                    <button className="button-secondary" onClick={() => confirmMeasurement(equipment, index)}>
                      Confirm
                    </button>
                  )}
                  <button className="button-link" onClick={() => markNotApplicable(equipment, index)}>
                    {measurement.not_applicable ? "Undo N/A" : "Not applicable"}
                  </button>
                  <button className="button-link danger" onClick={() => removeMeasurement(equipment, index)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <div className="reports-actions">
        <button className="button-secondary" onClick={onBack}>
          ← Photos
        </button>
        <button className="button-primary" onClick={onNext}>
          Next: Report →
        </button>
      </div>
    </div>
  );
}