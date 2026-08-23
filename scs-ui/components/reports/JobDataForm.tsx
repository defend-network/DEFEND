"use client";

import { useState } from "react";
import type { JobRecord } from "@/lib/reportTypes";
import type { SaveState } from "./JobFlow";

export function JobDataForm({
  record,
  commit,
  onNext,
}: {
  record: JobRecord;
  commit: (record: JobRecord) => void;
  onNext: () => void;
}) {
  const [categories, setCategories] = useState<string[]>(record.categories_tested ?? []);
  const [error, setError] = useState<string | null>(null);

  function setMetadata(field: string, value: string) {
    commit({
      ...record,
      metadata: { ...record.metadata, [field]: value },
    });
  }

  function toggleCategory(category: string) {
    const next = categories.includes(category)
      ? categories.filter((item) => item !== category)
      : [...categories, category];
    setCategories(next);
    commit({ ...record, categories_tested: next });
  }

  function next() {
    if (!record.metadata.project_name.trim() || !record.metadata.technician.trim()) {
      setError("Project name and technician are required before continuing.");
      return;
    }
    setError(null);
    onNext();
  }

  return (
    <div>
      <h4>Job data</h4>
      <div className="reports-grid-two">
        <label>
          Project name *
          <input
            value={record.metadata.project_name}
            onChange={(e) => setMetadata("project_name", e.target.value)}
          />
        </label>
        <label>
          Project number
          <input
            value={record.metadata.project_number ?? ""}
            onChange={(e) => setMetadata("project_number", e.target.value)}
          />
        </label>
        <label>
          Site name
          <input
            value={record.metadata.site_name}
            onChange={(e) => setMetadata("site_name", e.target.value)}
          />
        </label>
        <label>
          Site address
          <input
            value={record.metadata.site_address}
            onChange={(e) => setMetadata("site_address", e.target.value)}
          />
        </label>
        <label>
          Test date
          <input
            type="date"
            value={record.metadata.test_date ?? ""}
            onChange={(e) => setMetadata("test_date", e.target.value)}
          />
        </label>
        <label>
          Technician *
          <input
            value={record.metadata.technician}
            onChange={(e) => setMetadata("technician", e.target.value)}
          />
        </label>
        <label>
          Hiring contractor
          <input
            value={record.metadata.hiring_contractor ?? ""}
            onChange={(e) => setMetadata("hiring_contractor", e.target.value)}
          />
        </label>
        <label>
          Customer
          <input
            value={record.metadata.customer ?? ""}
            onChange={(e) => setMetadata("customer", e.target.value)}
          />
        </label>
        <label>
          Design engineer
          <input
            value={record.metadata.design_engineer ?? ""}
            onChange={(e) => setMetadata("design_engineer", e.target.value)}
          />
        </label>
      </div>
      <h4>Categories tested</h4>
      <div className="reports-chips">
        {["RTU", "AHU", "VAV", "FCU", "FAN", "VFD", "Exhaust", "Outside air", "Traverse", "Building pressure"].map(
          (category) => (
            <button
              key={category}
              type="button"
              className={categories.includes(category) ? "reports-chip active" : "reports-chip"}
              onClick={() => toggleCategory(category)}
            >
              {category}
            </button>
          ),
        )}
      </div>
      <h4>Notes & observations</h4>
      <div className="reports-grid-two">
        <label>
          Scope notes
          <textarea
            rows={3}
            value={record.scope_notes}
            onChange={(e) => commit({ ...record, scope_notes: e.target.value })}
          />
        </label>
        <label>
          Field observations
          <textarea
            rows={3}
            value={record.field_observations}
            onChange={(e) =>
              commit({ ...record, field_observations: e.target.value })
            }
          />
        </label>
        <label>
          Known deficiencies
          <textarea
            rows={3}
            value={record.known_deficiencies}
            onChange={(e) => commit({ ...record, known_deficiencies: e.target.value })}
          />
        </label>
        <label>
          Technician notes (report remarks)
          <textarea
            rows={3}
            value={record.technician_notes}
            onChange={(e) => commit({ ...record, technician_notes: e.target.value })}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="login-error">
          {error}
        </p>
      )}
      <div className="reports-actions">
        <button className="button-primary" onClick={next}>
          Next: Equipment →
        </button>
      </div>
    </div>
  );
}