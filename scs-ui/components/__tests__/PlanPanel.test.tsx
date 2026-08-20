import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { PlanPanel } from "../reports/PlanPanel";
import type { JobRecord } from "@/lib/reportTypes";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

function record(): JobRecord {
  return {
    metadata: {
      job_id: "1", project_name: "P", project_number: "1", site_name: "S", site_address: "A",
      test_date: "2026-08-18", technician: "T", hiring_contractor: null, customer: null,
      design_engineer: null, report_type: "TAB", created_at: "2026-08-18T00:00:00", updated_at: "2026-08-18T00:00:00",
    },
    scope_notes: "", field_observations: "", known_deficiencies: "", technician_notes: "",
    categories_tested: [], equipment: [], air_devices: [], traverses: [], environmental_readings: [],
    findings: [], photos: [], plan_overrides: [],
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/runtime-config")) {
        return jsonResponse({ scsApiOrigin: "http://127.0.0.1:8100" });
      }
      if (url.includes("/plan")) {
        return jsonResponse({ sections: ["cover", "certification", "closeout"] });
      }
      return jsonResponse({ detail: "unexpected " + url }, 404);
    }),
  );
});

test("shows included and excluded sections with reasons", async () => {
  render(
    <PlanPanel
      record={record()}
      commit={() => {}}
      planSections={["cover", "certification", "closeout"]}
      setPlanSections={() => {}}
    />,
  );
  await waitFor(() => expect(screen.getByText(/^Cover$/)).toBeInTheDocument());
  expect(screen.getByText(/^Certification$/)).toBeInTheDocument();
  expect(screen.getByText(/^RTU\/AHU nameplate data$/)).toBeInTheDocument();
  expect(screen.getAllByText(/no job content for this section/i).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/always included/i).length).toBeGreaterThan(0);
});

test("remove override records manual override and updates list", async () => {
  const recordWithOverrides = record();
  const commit = vi.fn();
  const setSections = vi.fn(
    (value: string[] | null | ((current: string[] | null) => string[] | null)) =>
      typeof value === "function"
        ? value(["cover", "certification", "closeout"])
        : value,
  );
  render(
    <PlanPanel
      record={recordWithOverrides}
      commit={commit}
      planSections={["cover", "certification", "closeout"]}
      setPlanSections={setSections}
    />,
  );
  await waitFor(() => expect(screen.getByText(/^Cover$/)).toBeInTheDocument());
  const removeButtons = screen.getAllByRole("button", { name: /^Remove$/ });
  fireEvent.click(removeButtons[0]);
  expect(commit).toHaveBeenCalledWith(
    expect.objectContaining({ plan_overrides: ["remove:cover"] }),
  );
  const updater = setSections.mock.calls[setSections.mock.calls.length - 1][0] as (
    current: string[] | null,
  ) => string[] | null;
  expect(updater(["cover", "certification", "closeout"])).toEqual(["certification", "closeout"]);
});

test("add override on excluded section records manual add", async () => {
  const commit = vi.fn();
  const setSections = vi.fn();
  render(
    <PlanPanel
      record={record()}
      commit={commit}
      planSections={["cover", "certification", "closeout"]}
      setPlanSections={setSections}
    />,
  );
  await waitFor(() => expect(screen.getByText(/^RTU\/AHU nameplate data$/)).toBeInTheDocument());
  const addButtons = screen.getAllByRole("button", { name: /^Add$/ });
  const target = addButtons.find((button) =>
    button.closest("li")?.textContent?.includes("RTU/AHU nameplate data"),
  );
  expect(target).toBeDefined();
  fireEvent.click(target!);
  expect(commit).toHaveBeenCalledWith(
    expect.objectContaining({ plan_overrides: ["add:rtu_nameplate"] }),
  );
});