import type { JobRecord, ValidationCheck } from "./reportTypes";

export type ReportStatus =
  | "DRAFT"
  | "EVIDENCE_INCOMPLETE"
  | "READY_TO_PLAN"
  | "PLANNED"
  | "VALIDATION_WARN"
  | "VALIDATION_BLOCK"
  | "READY_TO_EXPORT"
  | "EXPORTED";

export type ValidationGroup =
  | "MISSING REQUIRED"
  | "DATA CONFLICT"
  | "FORMULA"
  | "EVIDENCE"
  | "LAYOUT"
  | "OTHER";

const GROUP_MAP: Record<string, ValidationGroup> = {
  required_fields_complete: "MISSING REQUIRED",
  calculation_inputs_present: "MISSING REQUIRED",
  equipment_instances_consistent: "MISSING REQUIRED",
  design_vs_actual_consistent: "MISSING REQUIRED",
  no_duplicate_equipment: "DATA CONFLICT",
  calculation_outputs_correct: "DATA CONFLICT",
  no_formula_errors: "FORMULA",
  print_areas_valid: "FORMULA",
  no_orphan_evidence: "EVIDENCE",
  photo_refs_valid: "EVIDENCE",
  no_invented_measurements: "EVIDENCE",
  no_phantom_sections: "LAYOUT",
  no_phantom_equipment: "LAYOUT",
  no_placeholder_text: "LAYOUT",
  no_unexplained_required_blanks: "LAYOUT",
  workbook_opens_successfully: "LAYOUT",
  master_unchanged: "LAYOUT",
  measurement_units_valid: "OTHER",
};

export function validationGroup(check: ValidationCheck): ValidationGroup {
  return GROUP_MAP[check.name] ?? "OTHER";
}

export function hasContent(record: JobRecord): boolean {
  return (
    record.equipment.length > 0 ||
    record.air_devices.length > 0 ||
    record.traverses.length > 0 ||
    record.photos.length > 0 ||
    record.findings.length > 0
  );
}

export function hasAnyData(record: JobRecord): boolean {
  return (
    hasContent(record) ||
    record.scope_notes.trim() !== "" ||
    record.field_observations.trim() !== "" ||
    record.known_deficiencies.trim() !== "" ||
    record.technician_notes.trim() !== ""
  );
}

export function deriveStatus(
  record: JobRecord,
  planSections: string[] | null,
  lastValidation: { blocked: boolean; checks: ValidationCheck[] } | null,
  outputs: string[],
): ReportStatus {
  if (outputs.length > 0) {
    return "EXPORTED";
  }
  if (lastValidation) {
    if (lastValidation.blocked) {
      return "VALIDATION_BLOCK";
    }
    if (lastValidation.checks.some((c) => c.status === "WARN")) {
      return "VALIDATION_WARN";
    }
    return "READY_TO_EXPORT";
  }
  if (planSections && planSections.length > 0) {
    return "PLANNED";
  }
  if (hasContent(record)) {
    return "READY_TO_PLAN";
  }
  if (hasAnyData(record)) {
    return "EVIDENCE_INCOMPLETE";
  }
  return "DRAFT";
}

export function statusLabel(status: ReportStatus): string {
  return status.replace(/_/g, " ");
}

export function statusTone(status: ReportStatus): string {
  switch (status) {
    case "EXPORTED":
    case "READY_TO_EXPORT":
      return "status-ok";
    case "VALIDATION_BLOCK":
      return "status-bad";
    case "VALIDATION_WARN":
      return "status-warn";
    default:
      return "";
  }
}

export function sectionReason(section: string, overrides: string[]): string {
  const override = overrides.find((entry) => entry.endsWith(`:${section}`));
  if (override) {
    return override.startsWith("remove:")
      ? "Manual override — excluded by technician"
      : "Manual override — added by technician";
  }
  switch (section) {
    case "cover":
    case "certification":
    case "closeout":
      return "Always included";
    case "abbreviations":
    case "executive_summary":
      return "Job has equipment or findings";
    case "scope_summary":
      return "Job has scope notes or observations";
    case "rtu_nameplate":
      return "RTU/AHU equipment on job";
    case "building_pressure":
      return "Air devices recorded";
    case "traverse_summary":
    case "traverse_points":
      return "Traverses recorded";
    case "vav_data":
      return "VAV/FCU equipment on job";
    case "fan_test":
      return "Fan equipment on job";
    case "vfd_report":
      return "VFD equipment on job";
    case "photo_log":
      return "Photos attached";
    case "remarks":
      return "Notes or deficiencies recorded";
    default:
      return "Content-driven";
  }
}