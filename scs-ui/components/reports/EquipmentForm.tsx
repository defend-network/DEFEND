"use client";

import { FormEvent, useState } from "react";
import type { Equipment, JobRecord, Measurement } from "@/lib/reportTypes";
import { EQUIPMENT_TYPES, MEASUREMENT_FIELDS } from "@/lib/reportTypes";

type EquipmentDraft = {
  equipment_id: string;
  equipment_type: string;
  tag: string;
  manufacturer: string;
  model: string;
  serial: string;
  area_served: string;
};

function emptyEquipment(): EquipmentDraft {
  return { equipment_id: "", equipment_type: "RTU", tag: "", manufacturer: "", model: "", serial: "", area_served: "" };
}

export function EquipmentForm({
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
  const [draft, setDraft] = useState(emptyEquipment());
  const [error, setError] = useState<string | null>(null);

  function setDraftField(field: string, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  function addEquipment(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const id = draft.equipment_id.trim();
    if (!id) {
      setError("Equipment ID is required (e.g. RTU-1).");
      return;
    }
    if (record.equipment.some((item) => item.equipment_id === id)) {
      setError(`Equipment ${id} already exists.`);
      return;
    }
    commit({
      ...record,
      equipment: [
        ...record.equipment,
        {
          equipment_id: id,
          equipment_type: draft.equipment_type,
          tag: draft.tag.trim() || id,
          manufacturer: draft.manufacturer || null,
          model: draft.model || null,
          serial: draft.serial || null,
          area_served: draft.area_served || null,
          design_data: null,
          measurements: [],
          deficiencies: [],
          evidence_refs: [],
          notes: null,
        },
      ],
    });
    setDraft(emptyEquipment());
  }

  function removeEquipment(equipmentId: string) {
    commit({
      ...record,
      equipment: record.equipment.filter((item) => item.equipment_id !== equipmentId),
    });
  }

  function updateEquipment(equipment: Equipment) {
    commit({
      ...record,
      equipment: record.equipment.map((item) =>
        item.equipment_id === equipment.equipment_id ? equipment : item,
      ),
    });
  }

  function addMeasurement(equipment: Equipment, field: string, value: string, unit: string) {
    const numeric = value.trim() === "" ? null : Number(value);
    const measurement: Measurement = {
      field,
      value: value.trim() === "" ? null : Number.isFinite(numeric) ? numeric : value,
      unit,
      source_type: "TECH_ENTERED",
      source_ref: null,
      confidence: null,
      technician_confirmed: true,
      not_applicable: false,
      timestamp: new Date().toISOString(),
    };
    const existing = equipment.measurements.findIndex((m) => m.field === field);
    const measurements = [...equipment.measurements];
    if (existing >= 0) {
      measurements[existing] = measurement;
    } else {
      measurements.push(measurement);
    }
    updateEquipment({ ...equipment, measurements });
  }

  function markNotApplicable(equipment: Equipment, field: string) {
    const existing = equipment.measurements.findIndex((m) => m.field === field);
    const measurements = [...equipment.measurements];
    if (existing >= 0) {
      measurements[existing] = {
        ...measurements[existing],
        not_applicable: !measurements[existing].not_applicable,
      };
    } else {
      measurements.push({
        field,
        value: null,
        unit: "",
        source_type: "TECH_ENTERED",
        source_ref: null,
        confidence: null,
        technician_confirmed: true,
        not_applicable: true,
        timestamp: new Date().toISOString(),
      });
    }
    updateEquipment({ ...equipment, measurements });
  }

  function removeMeasurement(equipment: Equipment, index: number) {
    updateEquipment({
      ...equipment,
      measurements: equipment.measurements.filter((_, item) => item !== index),
    });
  }

  return (
    <div>
      <h4>Equipment</h4>
      <p className="muted">One card per unit. Add readings on the next step or inline here.</p>
      {record.equipment.length === 0 && <div className="empty">No equipment yet — add the first unit below.</div>}
      <div className="reports-equipment-grid">
        {record.equipment.map((equipment) => (
          <article className="reports-equipment-card" key={equipment.equipment_id}>
            <div className="reports-card-head">
              <span className="pill">{equipment.equipment_type}</span>
              <h5>{equipment.equipment_id}</h5>
              <button
                className="button-link danger"
                onClick={() => removeEquipment(equipment.equipment_id)}
              >
                Remove
              </button>
            </div>
            <div className="reports-grid-two">
              <label>
                Tag
                <input
                  value={equipment.tag}
                  onChange={(e) => updateEquipment({ ...equipment, tag: e.target.value })}
                />
              </label>
              <label>
                Manufacturer
                <input
                  value={equipment.manufacturer ?? ""}
                  onChange={(e) => updateEquipment({ ...equipment, manufacturer: e.target.value })}
                />
              </label>
              <label>
                Model
                <input
                  value={equipment.model ?? ""}
                  onChange={(e) => updateEquipment({ ...equipment, model: e.target.value })}
                />
              </label>
              <label>
                Serial
                <input
                  value={equipment.serial ?? ""}
                  onChange={(e) => updateEquipment({ ...equipment, serial: e.target.value })}
                />
              </label>
              <label>
                Area served
                <input
                  value={equipment.area_served ?? ""}
                  onChange={(e) => updateEquipment({ ...equipment, area_served: e.target.value })}
                />
              </label>
            </div>
            <h6>Readings</h6>
            {equipment.measurements.length === 0 && (
              <p className="muted">No readings recorded.</p>
            )}
            <ul className="reports-readings-list">
              {equipment.measurements.map((measurement, index) => (
                <li key={`${measurement.field}-${index}`}>
                  <span className="pill pill-field">{measurement.field}</span>
                  {measurement.not_applicable ? (
                    <span className="pill">N/A</span>
                  ) : (
                    <span>
                      {String(measurement.value)} {measurement.unit}
                    </span>
                  )}
                  {measurement.source_type.startsWith("AI_") && !measurement.technician_confirmed && (
                    <span className="pill pill-warn">needs confirmation</span>
                  )}
                  <button
                    className="button-link danger"
                    onClick={() => removeMeasurement(equipment, index)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <MeasurementQuickAdd equipment={equipment} onAdd={addMeasurement} onNA={markNotApplicable} />
          </article>
        ))}
      </div>
      <form className="reports-subform" onSubmit={addEquipment}>
        <h4>Add equipment</h4>
        <div className="reports-grid-two">
          <label>
            Equipment ID *
            <input
              value={draft.equipment_id}
              onChange={(e) => setDraftField("equipment_id", e.target.value)}
              placeholder="RTU-1"
            />
          </label>
          <label>
            Type
            <select value={draft.equipment_type} onChange={(e) => setDraftField("equipment_type", e.target.value)}>
              {EQUIPMENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </label>
          <label>
            Tag
            <input
              value={draft.tag}
              onChange={(e) => setDraftField("tag", e.target.value)}
              placeholder="RTU-1"
            />
          </label>
          <label>
            Manufacturer
            <input
              value={draft.manufacturer}
              onChange={(e) => setDraftField("manufacturer", e.target.value)}
            />
          </label>
          <label>
            Model
            <input
              value={draft.model}
              onChange={(e) => setDraftField("model", e.target.value)}
            />
          </label>
          <label>
            Serial
            <input
              value={draft.serial}
              onChange={(e) => setDraftField("serial", e.target.value)}
            />
          </label>
          <label>
            Area served
            <input
              value={draft.area_served}
              onChange={(e) => setDraftField("area_served", e.target.value)}
            />
          </label>
        </div>
        {error && (
          <p role="alert" className="login-error">
            {error}
          </p>
        )}
        <button className="button-primary" type="submit">
          Add equipment
        </button>
      </form>
      <div className="reports-actions">
        <button className="button-secondary" onClick={onBack}>
          ← Job
        </button>
        <button className="button-primary" onClick={onNext}>
          Next: Readings →
        </button>
      </div>
    </div>
  );
}

function MeasurementQuickAdd({
  equipment,
  onAdd,
  onNA,
}: {
  equipment: Equipment;
  onAdd: (equipment: Equipment, field: string, value: string, unit: string) => void;
  onNA: (equipment: Equipment, field: string) => void;
}) {
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  const suggested = MEASUREMENT_FIELDS[equipment.equipment_type.toLowerCase()] ?? MEASUREMENT_FIELDS.other;
  const chosen = field === "" ? suggested[0] : field;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!chosen || value.trim() === "") {
      return;
    }
    onAdd(equipment, chosen, value, unit);
    setValue("");
  }

  return (
    <form className="reports-inline-add" onSubmit={submit}>
      <select value={chosen} onChange={(e) => setField(e.target.value)}>
        {[...new Set([...suggested, "custom"])].map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
      <input
        placeholder="value"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        inputMode="decimal"
      />
      <input
        placeholder="unit (cfm, volts…)"
        value={unit}
        onChange={(e) => setUnit(e.target.value)}
      />
      <button type="submit" className="button-secondary">
        Add
      </button>
      <button
        type="button"
        className="button-link"
        onClick={() => {
          setValue("");
          onNA(equipment, chosen);
        }}
      >
        Mark N/A
      </button>
    </form>
  );
}