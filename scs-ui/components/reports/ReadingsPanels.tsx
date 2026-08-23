"use client";

import { FormEvent, useState } from "react";
import type { AirDevice, Finding, JobRecord, Traverse, TraversePoint } from "@/lib/reportTypes";

const DEVICE_FUNCTIONS = [
  "Outside Air",
  "Exhaust Air",
  "Supply Air",
  "Return Air",
  "General Exhaust",
  "Transfer",
];

export function ReadingsPanels({
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
  return (
    <div>
      <AirDevicesPanel record={record} commit={commit} />
      <TraversesPanel record={record} commit={commit} />
      <FindingsPanel record={record} commit={commit} />
      <div className="reports-actions">
        <button className="button-secondary" onClick={onBack}>
          ← Equipment
        </button>
        <button className="button-primary" onClick={onNext}>
          Next: Photos →
        </button>
      </div>
    </div>
  );
}

function AirDevicesPanel({ record, commit }: { record: JobRecord; commit: (record: JobRecord) => void }) {
  const [draft, setDraft] = useState({
    device_id: "",
    function: "Outside Air",
    area_served: "",
    design_cfm: "",
    as_found_cfm: "",
    final_cfm: "",
    measurement_method: "Velocity Grid",
    size: "",
    status: "MEASURED",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);

  function setField(field: string, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function addDevice(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const id = draft.device_id.trim();
    if (!id) {
      setError("Device ID is required (e.g. OA-1).");
      return;
    }
    if (record.air_devices.some((device) => device.device_id === id)) {
      setError(`Air device ${id} already exists.`);
      return;
    }
    const number = (value: string) => (value.trim() === "" ? null : Number(value));
    const device: AirDevice = {
      device_id: id,
      function: draft.function,
      area_served: draft.area_served || null,
      design_cfm: number(draft.design_cfm),
      as_found_cfm: number(draft.as_found_cfm),
      final_cfm: number(draft.final_cfm),
      measurement_method: draft.measurement_method || null,
      size: draft.size || null,
      avg_velocity_fpm: null,
      status: draft.status,
      notes: draft.notes || null,
      evidence_refs: [],
    };
    commit({ ...record, air_devices: [...record.air_devices, device] });
    setDraft({
      device_id: "",
      function: "Outside Air",
      area_served: "",
      design_cfm: "",
      as_found_cfm: "",
      final_cfm: "",
      measurement_method: "Velocity Grid",
      size: "",
      status: "MEASURED",
      notes: "",
    });
  }

  function removeDevice(deviceId: string) {
    commit({
      ...record,
      air_devices: record.air_devices.filter((device) => device.device_id !== deviceId),
    });
  }

  function updateDevice(device: AirDevice, field: string, value: string) {
    commit({
      ...record,
      air_devices: record.air_devices.map((item) =>
        item.device_id === device.device_id
          ? { ...item, [field]: field.endsWith("cfm") ? (value === "" ? null : Number(value)) : value }
          : item,
      ),
    });
  }

  return (
    <section className="reports-panel">
      <h4>Air devices</h4>
      <p className="muted">Outside air, exhaust, supply — design vs measured CFM. These drive the building pressurization sheet.</p>
      {record.air_devices.length === 0 && <div className="empty">No air devices yet.</div>}
      <div className="reports-device-list">
        {record.air_devices.map((device) => (
          <article className="reports-device-row" key={device.device_id}>
            <div className="reports-device-head">
              <span className="pill">{device.device_id}</span>
              <span>{device.function}</span>
              <button className="button-link danger" onClick={() => removeDevice(device.device_id)}>
                Remove
              </button>
            </div>
            <div className="reports-inline-fields">
              <label>
                Design CFM
                <input
                  inputMode="decimal"
                  value={device.design_cfm ?? ""}
                  onChange={(e) => updateDevice(device, "design_cfm", e.target.value)}
                />
              </label>
              <label>
                As-found CFM
                <input
                  inputMode="decimal"
                  value={device.as_found_cfm ?? ""}
                  onChange={(e) => updateDevice(device, "as_found_cfm", e.target.value)}
                />
              </label>
              <label>
                Final CFM
                <input
                  inputMode="decimal"
                  value={device.final_cfm ?? ""}
                  onChange={(e) => updateDevice(device, "final_cfm", e.target.value)}
                />
              </label>
              <label>
                Method
                <input
                  value={device.measurement_method ?? ""}
                  onChange={(e) => updateDevice(device, "measurement_method", e.target.value)}
                />
              </label>
              <label>
                Duct size
                <input
                  value={device.size ?? ""}
                  onChange={(e) => updateDevice(device, "size", e.target.value)}
                />
              </label>
              <label>
                Status
                <select value={device.status ?? ""} onChange={(e) => updateDevice(device, "status", e.target.value)}>
                  {["MEASURED", "FAIL", "DEFICIENT", "OK"].map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {device.notes && <p className="muted">{device.notes}</p>}
          </article>
        ))}
      </div>
      <form className="reports-subform" onSubmit={addDevice}>
        <h5>Add air device</h5>
        <div className="reports-grid-two">
          <label>
            Device ID *
            <input value={draft.device_id} onChange={(e) => setField("device_id", e.target.value)} placeholder="OA-1" />
          </label>
          <label>
            Function
            <select value={draft.function} onChange={(e) => setField("function", e.target.value)}>
              {DEVICE_FUNCTIONS.map((fn) => (
                <option key={fn} value={fn}>
                  {fn}
                </option>
              ))}
            </select>
          </label>
          <label>
            Area served
            <input value={draft.area_served} onChange={(e) => setField("area_served", e.target.value)} />
          </label>
          <label>
            Design CFM
            <input inputMode="decimal" value={draft.design_cfm} onChange={(e) => setField("design_cfm", e.target.value)} />
          </label>
          <label>
            As-found CFM
            <input inputMode="decimal" value={draft.as_found_cfm} onChange={(e) => setField("as_found_cfm", e.target.value)} />
          </label>
          <label>
            Final CFM
            <input inputMode="decimal" value={draft.final_cfm} onChange={(e) => setField("final_cfm", e.target.value)} />
          </label>
          <label>
            Method
            <input value={draft.measurement_method} onChange={(e) => setField("measurement_method", e.target.value)} />
          </label>
          <label>
            Duct size
            <input value={draft.size} onChange={(e) => setField("size", e.target.value)} placeholder="25.5x18.25" />
          </label>
        </div>
        {error && (
          <p role="alert" className="login-error">
            {error}
          </p>
        )}
        <button className="button-primary" type="submit">
          Add device
        </button>
      </form>
    </section>
  );
}

function TraversesPanel({ record, commit }: { record: JobRecord; commit: (record: JobRecord) => void }) {
  const [draft, setDraft] = useState({
    traverse_id: "",
    system_id: "",
    location: "",
    duct_size: "",
    area_sqft: "",
    design_fpm: "",
    final_fpm: "",
  });
  const [error, setError] = useState<string | null>(null);

  function addTraverse(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const id = draft.traverse_id.trim();
    if (!id) {
      setError("Traverse ID is required (e.g. TRV-1).");
      return;
    }
    const number = (value: string) => (value.trim() === "" ? null : Number(value));
    const traverse: Traverse = {
      traverse_id: id,
      system_id: draft.system_id.trim() || id,
      location: draft.location.trim(),
      duct_size: draft.duct_size || null,
      area_sqft: number(draft.area_sqft),
      design_fpm: number(draft.design_fpm),
      final_fpm: number(draft.final_fpm),
      points: [],
      evidence_refs: [],
    };
    commit({ ...record, traverses: [...record.traverses, traverse] });
    setDraft({ traverse_id: "", system_id: "", location: "", duct_size: "", area_sqft: "", design_fpm: "", final_fpm: "" });
  }

  function removeTraverse(traverseId: string) {
    commit({
      ...record,
      traverses: record.traverses.filter((traverse) => traverse.traverse_id !== traverseId),
    });
  }

  function updateTraverse(traverse: Traverse, field: string, value: string) {
    const numeric = ["area_sqft", "design_fpm", "final_fpm"].includes(field);
    commit({
      ...record,
      traverses: record.traverses.map((item) =>
        item.traverse_id === traverse.traverse_id
          ? { ...item, [field]: numeric ? (value === "" ? null : Number(value)) : value }
          : item,
      ),
    });
  }

  function updatePoint(traverse: Traverse, index: number, field: string, value: string) {
    const points = traverse.points.map((point, item) =>
      item === index
        ? { ...point, [field]: field === "fpm" ? (value === "" ? null : Number(value)) : value }
        : point,
    );
    commit({
      ...record,
      traverses: record.traverses.map((item) => (item.traverse_id === traverse.traverse_id ? { ...item, points } : item)),
    });
  }

  function addPoint(traverse: Traverse) {
    const nextLabel = String.fromCharCode(65 + traverse.points.length);
    const point: TraversePoint = { row_label: nextLabel, fpm: null, column: 1 };
    commit({
      ...record,
      traverses: record.traverses.map((item) =>
        item.traverse_id === traverse.traverse_id ? { ...item, points: [...item.points, point] } : item,
      ),
    });
  }

  return (
    <section className="reports-panel">
      <h4>Duct traverses</h4>
      <p className="muted">FPM per point with duct area; the report computes CFM = FPM × area.</p>
      {record.traverses.length === 0 && <div className="empty">No traverses yet.</div>}
      {record.traverses.map((traverse) => (
        <article className="reports-device-row" key={traverse.traverse_id}>
          <div className="reports-device-head">
            <span className="pill">{traverse.traverse_id}</span>
            <span>{traverse.location}</span>
            <button className="button-link danger" onClick={() => removeTraverse(traverse.traverse_id)}>
              Remove
            </button>
          </div>
          <div className="reports-inline-fields">
            <label>
              System
              <input value={traverse.system_id} onChange={(e) => updateTraverse(traverse, "system_id", e.target.value)} />
            </label>
            <label>
              Location
              <input value={traverse.location} onChange={(e) => updateTraverse(traverse, "location", e.target.value)} />
            </label>
            <label>
              Duct size
              <input value={traverse.duct_size ?? ""} onChange={(e) => updateTraverse(traverse, "duct_size", e.target.value)} />
            </label>
            <label>
              Area (sq ft)
              <input inputMode="decimal" value={traverse.area_sqft ?? ""} onChange={(e) => updateTraverse(traverse, "area_sqft", e.target.value)} />
            </label>
            <label>
              Design FPM
              <input inputMode="decimal" value={traverse.design_fpm ?? ""} onChange={(e) => updateTraverse(traverse, "design_fpm", e.target.value)} />
            </label>
            <label>
              Final FPM
              <input inputMode="decimal" value={traverse.final_fpm ?? ""} onChange={(e) => updateTraverse(traverse, "final_fpm", e.target.value)} />
            </label>
          </div>
          <div className="reports-traverse-points">
            {traverse.points.map((point, index) => (
              <label key={`${point.row_label}-${index}`}>
                {point.row_label}
                <input
                  inputMode="decimal"
                  placeholder="FPM"
                  value={point.fpm ?? ""}
                  onChange={(e) => updatePoint(traverse, index, "fpm", e.target.value)}
                />
              </label>
            ))}
            <button className="button-secondary" type="button" onClick={() => addPoint(traverse)}>
              + Point
            </button>
          </div>
        </article>
      ))}
      <form className="reports-subform" onSubmit={addTraverse}>
        <h5>Add traverse</h5>
        <div className="reports-grid-two">
          <label>
            Traverse ID *
            <input value={draft.traverse_id} onChange={(e) => setDraft({ ...draft, traverse_id: e.target.value })} placeholder="TRV-1" />
          </label>
          <label>
            System ID
            <input value={draft.system_id} onChange={(e) => setDraft({ ...draft, system_id: e.target.value })} placeholder="OAU-2" />
          </label>
          <label>
            Location
            <input value={draft.location} onChange={(e) => setDraft({ ...draft, location: e.target.value })} placeholder="Catwalk" />
          </label>
          <label>
            Duct size
            <input value={draft.duct_size} onChange={(e) => setDraft({ ...draft, duct_size: e.target.value })} placeholder="18X16" />
          </label>
          <label>
            Area (sq ft)
            <input inputMode="decimal" value={draft.area_sqft} onChange={(e) => setDraft({ ...draft, area_sqft: e.target.value })} />
          </label>
          <label>
            Design FPM
            <input inputMode="decimal" value={draft.design_fpm} onChange={(e) => setDraft({ ...draft, design_fpm: e.target.value })} />
          </label>
          <label>
            Final FPM
            <input inputMode="decimal" value={draft.final_fpm} onChange={(e) => setDraft({ ...draft, final_fpm: e.target.value })} />
          </label>
        </div>
        {error && (
          <p role="alert" className="login-error">
            {error}
          </p>
        )}
        <button className="button-primary" type="submit">
          Add traverse
        </button>
      </form>
    </section>
  );
}

function FindingsPanel({ record, commit }: { record: JobRecord; commit: (record: JobRecord) => void }) {
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState("");
  const [error, setError] = useState<string | null>(null);

  function addFinding(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!title.trim()) {
      setError("Finding title is required.");
      return;
    }
    const finding: Finding = {
      finding_id: null,
      title: title.trim(),
      details: details.trim(),
      severity: "open",
      evidence_refs: [],
    };
    commit({ ...record, findings: [...record.findings, finding] });
    setTitle("");
    setDetails("");
  }

  function removeFinding(index: number) {
    commit({
      ...record,
      findings: record.findings.filter((_, item) => item !== index),
    });
  }

  return (
    <section className="reports-panel">
      <h4>Findings</h4>
      <p className="muted">Deficiencies and observations that belong in the report.</p>
      {record.findings.length === 0 && <div className="empty">No findings recorded.</div>}
      <ul className="reports-readings-list">
        {record.findings.map((finding, index) => (
          <li key={`${finding.title}-${index}`}>
            <strong>{finding.title}</strong>
            {finding.details && <span className="muted"> — {finding.details}</span>}
            <button className="button-link danger" onClick={() => removeFinding(index)}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <form className="reports-subform" onSubmit={addFinding}>
        <div className="reports-grid-two">
          <label>
            Finding *
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="OA damper closed" />
          </label>
          <label>
            Details
            <input value={details} onChange={(e) => setDetails(e.target.value)} placeholder="What you observed" />
          </label>
        </div>
        {error && (
          <p role="alert" className="login-error">
            {error}
          </p>
        )}
        <button className="button-primary" type="submit">
          Add finding
        </button>
      </form>
    </section>
  );
}