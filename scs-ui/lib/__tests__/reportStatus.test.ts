import { describe, expect, test } from "vitest";
import {
  deriveStatus,
  sectionReason,
  validationGroup,
} from "@/lib/reportStatus";
import type { JobRecord, ValidationCheck } from "@/lib/reportTypes";

function record(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    metadata: {
      job_id: "1",
      project_name: "P",
      project_number: "1",
      site_name: "S",
      site_address: "A",
      test_date: "2026-08-18",
      technician: "T",
      hiring_contractor: null,
      customer: null,
      design_engineer: null,
      report_type: "TAB",
      created_at: "2026-08-18T00:00:00",
      updated_at: "2026-08-18T00:00:00",
    },
    scope_notes: "",
    field_observations: "",
    known_deficiencies: "",
    technician_notes: "",
    categories_tested: [],
    equipment: [],
    air_devices: [],
    traverses: [],
    environmental_readings: [],
    findings: [],
    photos: [],
    plan_overrides: [],
    ...overrides,
  };
}

const check = (name: string, status: "PASS" | "WARN" | "BLOCK"): ValidationCheck => ({
  name,
  status,
  message: name,
});

describe("deriveStatus", () => {
  test("empty job is DRAFT", () => {
    expect(deriveStatus(record(), null, null, [])).toBe("DRAFT");
  });

  test("notes only is EVIDENCE_INCOMPLETE", () => {
    expect(deriveStatus(record({ scope_notes: "notes" }), null, null, [])).toBe(
      "EVIDENCE_INCOMPLETE",
    );
  });

  test("equipment present is READY_TO_PLAN", () => {
    expect(
      deriveStatus(
        record({
          equipment: [
            {
              equipment_id: "RTU-1",
              equipment_type: "RTU",
              tag: "RTU-1",
              manufacturer: null,
              model: null,
              serial: null,
              area_served: null,
              design_data: null,
              measurements: [],
              deficiencies: [],
              evidence_refs: [],
              notes: null,
            },
          ],
        }),
        null,
        null,
        [],
      ),
    ).toBe("READY_TO_PLAN");
  });

  test("planned with sections is PLANNED", () => {
    expect(deriveStatus(record(), ["cover", "certification"], null, [])).toBe("PLANNED");
  });

  test("validation block dominates", () => {
    expect(
      deriveStatus(record(), ["cover"], { blocked: true, checks: [check("no_formula_errors", "BLOCK")] }, []),
    ).toBe("VALIDATION_BLOCK");
  });

  test("validation warn dominates over warn-free", () => {
    expect(
      deriveStatus(record(), ["cover"], { blocked: false, checks: [check("a", "WARN")] }, []),
    ).toBe("VALIDATION_WARN");
  });

  test("clean validation is READY_TO_EXPORT", () => {
    expect(
      deriveStatus(record(), ["cover"], { blocked: false, checks: [check("a", "PASS")] }, []),
    ).toBe("READY_TO_EXPORT");
  });

  test("existing outputs are EXPORTED", () => {
    expect(
      deriveStatus(record(), ["cover"], { blocked: true, checks: [] }, ["P_TAB_2026-08-18.xlsx"]),
    ).toBe("EXPORTED");
  });
});

describe("validationGroup", () => {
  test("maps checks to P8 groups", () => {
    expect(validationGroup(check("required_fields_complete", "PASS"))).toBe("MISSING REQUIRED");
    expect(validationGroup(check("no_duplicate_equipment", "PASS"))).toBe("DATA CONFLICT");
    expect(validationGroup(check("no_formula_errors", "PASS"))).toBe("FORMULA");
    expect(validationGroup(check("no_orphan_evidence", "PASS"))).toBe("EVIDENCE");
    expect(validationGroup(check("no_phantom_sections", "PASS"))).toBe("LAYOUT");
    expect(validationGroup(check("measurement_units_valid", "PASS"))).toBe("OTHER");
  });
});

describe("sectionReason", () => {
  test("shows override provenance", () => {
    expect(sectionReason("building_pressure", ["remove:building_pressure"])).toContain(
      "Manual override",
    );
    expect(sectionReason("fan_test", ["add:fan_test"])).toContain("Manual override");
  });

  test("explains content-driven inclusion", () => {
    expect(sectionReason("rtu_nameplate", [])).toContain("RTU/AHU");
    expect(sectionReason("cover", [])).toBe("Always included");
  });
});