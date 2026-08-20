import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ReportsHome } from "../reports/ReportsHome";
import { ApiError } from "@/lib/api";

vi.mock("@/lib/reportsApi", () => ({
  listJobs: vi.fn(),
  listOutputs: vi.fn(async () => ({ outputs: [] })),
  getJob: vi.fn(async () => null),
}));

import { listJobs } from "@/lib/reportsApi";

const summary = {
  job_id: "2026-0190",
  project_name: "Meridian Retail",
  project_number: "2026-0190",
  site_name: "Meridian",
  site_address: "1 Main St",
  test_date: "2026-08-19",
  technician: "Taylor",
  hiring_contractor: "Field Ready Mechanical",
  customer: null,
  design_engineer: null,
  report_type: "TAB",
  created_at: "2026-08-19T10:00:00",
  updated_at: "2026-08-19T10:00:00",
};

beforeEach(() => {
  vi.mocked(listJobs).mockReset();
});

test("shows the loading state while the request is pending", () => {
  vi.mocked(listJobs).mockReturnValue(new Promise(() => {}));
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  expect(screen.getByText("Loading reports…")).toBeInTheDocument();
});

test("renders the report list after a successful load", async () => {
  vi.mocked(listJobs).mockResolvedValue({ jobs: [summary] });
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText("Meridian Retail")).toBeInTheDocument(),
  );
});

test("shows an empty state with a new report action when there are zero reports", async () => {
  vi.mocked(listJobs).mockResolvedValue({ jobs: [] });
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText(/No field reports yet/)).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /new report/i })).toBeInTheDocument();
});

test("shows an actionable error with Retry when the request fails", async () => {
  vi.mocked(listJobs).mockRejectedValue(new Error("Could not reach the SCS API"));
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  await waitFor(() => expect(screen.getByText("Could not reach the SCS API")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("shows an auth-expired message on 401", async () => {
  vi.mocked(listJobs).mockRejectedValue(new ApiError("Authentication required", 401));
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  await waitFor(() =>
    expect(screen.getByText(/session has expired/i)).toBeInTheDocument(),
  );
});

test("never remains on Loading reports… after a failed request (leaves loading phase)", async () => {
  vi.mocked(listJobs).mockRejectedValue(new Error("boom"));
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  await waitFor(() => expect(screen.queryByText("Loading reports…")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("Retry re-issues the request and recovers", async () => {
  vi.mocked(listJobs)
    .mockRejectedValueOnce(new Error("boom"))
    .mockResolvedValueOnce({ jobs: [summary] });
  render(<ReportsHome defaultTechnician="Taylor" onOpen={() => {}} />);
  const retry = await screen.findByRole("button", { name: "Retry" });
  retry.click();
  await waitFor(() => expect(screen.getByText("Meridian Retail")).toBeInTheDocument());
});