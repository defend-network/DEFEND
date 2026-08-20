import { api } from "./api";
import type {
  AirDevice,
  ComposeResult,
  Contractor,
  Equipment,
  Finding,
  JobRecord,
  Measurement,
  PhotoEvidence,
  Traverse,
} from "./reportTypes";

export type JobSummary = {
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

export function listContractors(): Promise<{ contractors: Contractor[] }> {
  return api("/api/scs/reports/contractors");
}

export function addContractor(input: {
  name: string;
  contact?: string | null;
  phone?: string | null;
  email?: string | null;
}): Promise<Contractor> {
  return api("/api/scs/reports/contractors", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listJobs(): Promise<{ jobs: JobSummary[] }> {
  return api("/api/scs/reports/jobs");
}

export function createJob(input: {
  project_name: string;
  project_number: string;
  site_name: string;
  site_address: string;
  test_date: string;
  technician: string;
  hiring_contractor?: string | null;
}): Promise<JobRecord> {
  return api("/api/scs/reports/jobs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getJob(jobId: string): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}`);
}

export function replaceJob(jobId: string, record: JobRecord): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}`, {
    method: "PUT",
    body: JSON.stringify(record),
  });
}

export function addEquipment(
  jobId: string,
  input: {
    equipment_id: string;
    equipment_type: string;
    tag: string;
    manufacturer?: string | null;
    model?: string | null;
    serial?: string | null;
    area_served?: string | null;
  },
): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}/equipment`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addMeasurement(
  jobId: string,
  equipmentId: string,
  input: {
    field: string;
    value: number | string | null;
    unit: string;
    source_type?: string;
    technician_confirmed?: boolean;
    not_applicable?: boolean;
  },
): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}/equipment/${equipmentId}/measurements`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addAirDevice(
  jobId: string,
  input: Omit<AirDevice, "evidence_refs">,
): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}/air-devices`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addTraverse(
  jobId: string,
  input: Omit<Traverse, "evidence_refs">,
): Promise<JobRecord> {
  return api(`/api/scs/reports/jobs/${jobId}/traverses`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addFinding(jobId: string, input: Finding): Promise<Finding> {
  return api(`/api/scs/reports/jobs/${jobId}/findings`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getPlan(jobId: string): Promise<{ sections: string[] }> {
  return api(`/api/scs/reports/jobs/${jobId}/plan`);
}

export function composeReport(jobId: string): Promise<ComposeResult> {
  return api(`/api/scs/reports/jobs/${jobId}/compose`, { method: "POST" });
}

export function listOutputs(jobId: string): Promise<{ outputs: string[] }> {
  return api(`/api/scs/reports/jobs/${jobId}/outputs`);
}

export function visionStatus(): Promise<{ status: string; provider: string | null; note: string }> {
  return api("/api/scs/reports/vision/status");
}

export function downloadUrl(jobId: string, filename: string): Promise<string> {
  return resolveApiOrigin().then(
    (origin) => `${origin}/api/scs/reports/jobs/${jobId}/outputs/${encodeURIComponent(filename)}`,
  );
}

async function resolveApiOrigin(): Promise<string> {
  try {
    const response = await fetch("/api/runtime-config", { cache: "no-store" });
    if (response.ok) {
      const payload = (await response.json()) as { scsApiOrigin?: string };
      if (payload.scsApiOrigin) {
        return payload.scsApiOrigin;
      }
    }
  } catch {
    // fall through
  }
  return "http://127.0.0.1:8100";
}

export function uploadPhotos(
  jobId: string,
  files: File[],
  onProgress: (uploaded: number, total: number) => void,
): Promise<{ photos: PhotoEvidence[] }> {
  return resolveApiOrigin().then(
    (origin) =>
      new Promise((resolve, reject) => {
        const form = new FormData();
        for (const file of files) {
          form.append("files", file, file.name);
        }
        const request = new XMLHttpRequest();
        request.open("POST", `${origin}/api/scs/reports/jobs/${jobId}/photos`);
        request.withCredentials = true;
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            onProgress(event.loaded, event.total);
          }
        };
        request.onload = () => {
          if (request.status >= 200 && request.status < 300) {
            try {
              resolve(JSON.parse(request.responseText) as { photos: PhotoEvidence[] });
            } catch {
              reject(new Error("Upload succeeded but response was unreadable"));
            }
          } else {
            let message = "Photo upload failed";
            try {
              const payload = JSON.parse(request.responseText) as { detail?: string };
              if (payload.detail) {
                message = payload.detail;
              }
            } catch {
              // keep generic message
            }
            reject(new Error(message));
          }
        };
        request.onerror = () => reject(new Error("Photo upload failed — check connection"));
        request.send(form);
      }),
  );
}

export function recordHasField(
  record: JobRecord,
  equipmentId: string,
  field: string,
): boolean {
  const equipment = record.equipment.find((e) => e.equipment_id === equipmentId);
  if (!equipment) {
    return false;
  }
  return equipment.measurements.some(
    (m) => m.field === field && (m.value !== null || m.not_applicable),
  );
}

export type { Measurement, Equipment };