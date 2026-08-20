import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { NewJobForm } from "../reports/NewJobForm";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/runtime-config")) {
      return jsonResponse({ scsApiOrigin: "http://127.0.0.1:8100" });
    }
    if (url.endsWith("/api/scs/reports/contractors") && (!init?.method || init.method === "GET")) {
      return jsonResponse({ contractors: [{ company_name: "Remedy Heating and Cooling", contact: null, email: null, phone: null, address: null, notes: null }] });
    }
    if (url.endsWith("/api/scs/reports/contractors") && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return jsonResponse({ company_name: body.name, contact: body.contact, email: body.email, phone: body.phone, address: null, notes: null }, 201);
    }
    if (url.endsWith("/api/scs/reports/jobs") && init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      return jsonResponse({
        metadata: { job_id: "777", project_name: body.project_name, project_number: body.project_number, site_name: body.site_name, site_address: body.site_address, test_date: body.test_date, technician: body.technician, hiring_contractor: body.hiring_contractor, customer: null, design_engineer: null, report_type: "TAB", created_at: "2026-08-18T00:00:00", updated_at: "2026-08-18T00:00:00" },
        scope_notes: "", field_observations: "", known_deficiencies: "", technician_notes: "", categories_tested: [],
        equipment: [], air_devices: [], traverses: [], environmental_readings: [], findings: [], photos: [], plan_overrides: [],
      }, 201);
    }
    return jsonResponse({ detail: "unexpected " + url }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

test("creates a job with a selected existing contractor", async () => {
  const onCreated = vi.fn();
  render(<NewJobForm defaultTechnician="Aaron" onCreated={onCreated} onCancel={() => {}} />);
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /Remedy Heating and Cooling/i })).toBeInTheDocument(),
  );
  fireEvent.change(screen.getByLabelText(/project name/i), { target: { value: "Crunch Fitness" } });
  fireEvent.change(screen.getByLabelText(/project number/i), { target: { value: "2026-0147" } });
  fireEvent.change(screen.getByLabelText(/hiring contractor/i), {
    target: { value: "Remedy Heating and Cooling" },
  });
  fireEvent.click(screen.getByRole("button", { name: /create job/i }));
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
  const record = onCreated.mock.calls[0][0];
  expect(record.metadata.hiring_contractor).toBe("Remedy Heating and Cooling");
  expect(record.metadata.technician).toBe("Aaron");
});

test("adds a contractor inline and selects it immediately", async () => {
  render(<NewJobForm defaultTechnician="Aaron" onCreated={() => {}} onCancel={() => {}} />);
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /Remedy Heating and Cooling/i })).toBeInTheDocument(),
  );
  fireEvent.click(screen.getByRole("button", { name: /add contractor/i }));
  const nameInput = screen.getByLabelText(/company name/i);
  fireEvent.change(nameInput, { target: { value: "NewCo HVAC" } });
  fireEvent.click(screen.getByRole("button", { name: /save contractor/i }));
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /NewCo HVAC/i })).toBeInTheDocument(),
  );
  expect(screen.getByLabelText(/hiring contractor/i)).toHaveValue("NewCo HVAC");
  const postCalls = fetchMock.mock.calls.filter(
    ([url, init]) => String(url).endsWith("/api/scs/reports/contractors") && init?.method === "POST",
  );
  expect(postCalls).toHaveLength(1);
  expect(JSON.parse(String(postCalls[0][1].body)).name).toBe("NewCo HVAC");
});

test("requires project name and number", async () => {
  render(<NewJobForm defaultTechnician="Aaron" onCreated={() => {}} onCancel={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: /create job/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/project name and project number are required/i);
});