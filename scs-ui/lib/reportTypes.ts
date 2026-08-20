export type Contractor = {
  company_name: string;
  contact: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  notes: string | null;
};

export type Measurement = {
  field: string;
  value: number | string | null;
  unit: string;
  source_type: string;
  source_ref: string | null;
  confidence: number | null;
  technician_confirmed: boolean;
  not_applicable: boolean;
  timestamp: string | null;
};

export type Equipment = {
  equipment_id: string;
  equipment_type: string;
  tag: string;
  manufacturer: string | null;
  model: string | null;
  serial: string | null;
  area_served: string | null;
  design_data: Record<string, unknown> | null;
  measurements: Measurement[];
  deficiencies: string[];
  evidence_refs: string[];
  notes: string | null;
};

export type AirDevice = {
  device_id: string;
  function: string;
  area_served: string | null;
  design_cfm: number | null;
  as_found_cfm: number | null;
  final_cfm: number | null;
  measurement_method: string | null;
  size: string | null;
  avg_velocity_fpm: number | null;
  status: string | null;
  notes: string | null;
  evidence_refs: string[];
};

export type TraversePoint = {
  row_label: string;
  fpm: number | null;
  column: number | null;
};

export type Traverse = {
  traverse_id: string;
  system_id: string;
  location: string;
  duct_size: string | null;
  area_sqft: number | null;
  design_fpm: number | null;
  final_fpm: number | null;
  points: TraversePoint[];
  evidence_refs: string[];
};

export type Finding = {
  finding_id: string | null;
  title: string;
  details: string;
  severity: string;
  evidence_refs: string[];
};

export type PhotoEvidence = {
  photo_id: string;
  original_filename: string;
  sha256: string;
  classification: string | null;
  captured_at: string | null;
  equipment_association: string | null;
  candidate_facts: unknown[];
  confidence: number | null;
  review_status: string;
};

export type JobMetadata = {
  job_id: string;
  project_name: string;
  project_number: string | null;
  site_name: string;
  site_address: string;
  test_date: string | null;
  technician: string;
  hiring_contractor: string | null;
  customer: string | null;
  design_engineer: string | null;
  report_type: string;
  created_at: string;
  updated_at: string;
};

export type JobRecord = {
  metadata: JobMetadata;
  scope_notes: string;
  field_observations: string;
  known_deficiencies: string;
  technician_notes: string;
  categories_tested: string[];
  equipment: Equipment[];
  air_devices: AirDevice[];
  traverses: Traverse[];
  environmental_readings: unknown[];
  findings: Finding[];
  photos: PhotoEvidence[];
  plan_overrides: string[];
};

export type ValidationCheck = {
  name: string;
  status: "PASS" | "WARN" | "BLOCK";
  message: string;
};

export type ComposeResult = {
  output: string;
  blocked: boolean;
  checks: ValidationCheck[];
};

export const EQUIPMENT_TYPES = [
  "RTU",
  "AHU",
  "FCU",
  "VAV",
  "FAN",
  "VFD",
  "EXHAUST",
  "OUTSIDE_AIR",
  "OTHER",
] as const;

export const SECTION_TITLES: Record<string, string> = {
  cover: "Cover",
  certification: "Certification",
  abbreviations: "Abbreviations",
  executive_summary: "Executive summary",
  scope_summary: "Scope summary",
  rtu_nameplate: "RTU/AHU nameplate data",
  building_pressure: "Building pressurization",
  traverse_summary: "Duct traverse summary",
  traverse_points: "Traverse point data",
  vav_data: "VAV data",
  fan_test: "Fan test",
  vfd_report: "VFD report",
  photo_log: "Photo log",
  remarks: "Remarks",
  closeout: "Final closeout",
};

export const SECTION_GROUPS: Record<string, string> = {
  cover: "Opening",
  certification: "Opening",
  abbreviations: "Opening",
  executive_summary: "Opening",
  scope_summary: "Opening",
  rtu_nameplate: "Equipment",
  building_pressure: "Air distribution",
  traverse_summary: "Air distribution",
  traverse_points: "Air distribution",
  vav_data: "Air distribution",
  fan_test: "Equipment",
  vfd_report: "Equipment",
  photo_log: "Evidence",
  remarks: "Evidence",
  closeout: "Closing",
};

export const MEASUREMENT_FIELDS: Record<string, string[]> = {
  rtu: ["airflow_cfm", "voltage", "refrigerant", "economizer", "gas_input"],
  ahu: ["airflow_cfm", "voltage", "refrigerant", "economizer"],
  fcu: ["airflow_cfm", "voltage"],
  vav: ["design_min", "design_max", "airflow_cfm"],
  fan: ["airflow_cfm", "voltage", "rpm"],
  vfd: ["voltage", "amps", "hz"],
  exhaust: ["airflow_cfm", "voltage"],
  outside_air: ["airflow_cfm", "voltage"],
  other: ["notes"],
};